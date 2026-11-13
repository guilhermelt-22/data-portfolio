"""Offline tests: the fictitious files are rebuilt in a temporary folder, so nothing here needs the network."""
from __future__ import annotations

import pandas as pd
import pytest

from vendorfeed import generate
from vendorfeed.checks import run_checks
from vendorfeed.clean import parse_barcode, parse_money, parse_qty, parse_weight, style_title
from vendorfeed.read import read_supplier
from vendorfeed.run import process
from vendorfeed.shopify import TEMPLATE, write_csv

P = generate.PLANTED


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("vendorfeed")
    oct_path, nov_path, expected = generate.build(folder=tmp / "input")
    first = process(oct_path, tmp / "october")
    second = process(nov_path, tmp / "november", previous=tmp / "october")
    return first, second, expected, tmp


def issues(log, text):
    return log[log["issue"].str.contains(text, regex=False)]


# --- parsing ---------------------------------------------------------------------------------------------

def test_parse_barcode_cases():
    assert parse_barcode(36000291452) == ("036000291452", "restored_zero")      # leading zero dropped by Excel
    assert parse_barcode("036000291452") == ("036000291452", "ok")
    good = "84012345678" + str(generate.upc_check_digit("84012345678"))
    assert parse_barcode(int(good)) == (good, "ok")
    assert parse_barcode("8.40123E+11") == ("", "scientific")
    assert parse_barcode("036000291453") == ("", "bad_check")
    assert parse_barcode(None) == ("", "missing")


def test_parse_money_qty_weight():
    assert parse_money("$12.50") == 12.5 and parse_money(" 1,299.00 USD") == 1299.0 and parse_money("") is None
    assert parse_qty("50+") == (50, "at_least") and parse_qty("-") == (0, "not_a_number") and parse_qty(12) == (12, "ok")
    assert parse_weight("3.2 oz") == 91 and parse_weight("1.1 lbs") == 499 and parse_weight("250g") == 250
    assert parse_weight("0.38 kg") == 380 and parse_weight("heavy") is None


def test_style_title_strips_colour_and_size():
    descs = ["MERINO HIKER SOCK NAVY LG", "MERINO HIKER SOCK NVY S", "MERINO HIKER SOCK BLACK M"]
    assert style_title(descs, ["Navy", "Black"], ["L", "S", "M"]) == "Merino Hiker Sock"
    assert style_title(["GRIP TRAIL GLOVE HTHR GREY S", "GRIP TRAIL GLOVE HTHR GREY M"], ["Heather Grey"], ["S", "M"]) == "Grip Trail Glove"
    assert style_title(["COMMUTER ROLL-TOP PACK OLIVE 20L", "COMMUTER ROLL-TOP PACK OLV 30L"], ["Olive"], ["20 L", "30 L"]) == "Commuter Roll-Top Pack"


# --- reading the file as it arrives ----------------------------------------------------------------------

def test_header_found_below_title_rows_and_rows_labelled(runs):
    first, _, _, _ = runs
    assert first["layout"].header_row == 4
    k = first["kinds"]
    assert (k.get("title"), k.get("banner"), k.get("note")) == (P["title_rows"], P["banner_rows"], P["note_rows"])


def test_renamed_and_reordered_columns_are_mapped(runs):
    _, second, _, _ = runs
    mapped = second["layout"].mapped
    assert mapped["SKU"] == "sku" and mapped["Product Name"] == "description" and mapped["Retail"] == "retail"
    assert mapped["Wholesale Price"] == "wholesale" and mapped["Qty"] == "qty" and not second["layout"].ignored


# --- every planted problem is caught ---------------------------------------------------------------------

def test_duplicates_and_conflicts(runs):
    first, _, _, _ = runs
    rows = first["rows"]
    assert (rows["fate"] == "duplicate removed").sum() == P["exact_duplicates"]
    held = rows[rows["fate"] == "held back"]
    conflicts = held[held["reason"].str.contains("with different values")]
    assert conflicts["sku"].nunique() == P["conflicting_skus"] and len(conflicts) == 2 * P["conflicting_skus"]
    pairs = held[held["reason"].str.contains("Which SKU should")]
    assert len(pairs) == 2 * P["duplicate_option_pairs"]
    assert (held["reason"].str.startswith("No wholesale or retail price")).sum() == P["rows_without_any_price"]


def test_discontinued_rows_excluded(runs):
    first, _, _, _ = runs
    assert (first["rows"]["fate"] == "excluded").sum() == P["discontinued_rows"]


def test_barcodes(runs):
    first, _, _, _ = runs
    log = first["log"]
    assert len(issues(log, "scientific notation")) == P["barcode_scientific"]
    assert len(issues(log, "fails the check digit")) == P["barcode_bad_check_digit"]
    restored = issues(log, "has 11 digits")
    assert len(restored) == P["barcode_lost_zero"]
    v = first["variants"].set_index("sku")
    assert all(v.loc[s, "barcode"].startswith("0") and len(v.loc[s, "barcode"]) == 12 for s in restored["sku"])


def test_prices_stock_images(runs):
    first, _, _, _ = runs
    v, log = first["variants"], first["log"]
    assert v.loc[v["priced_by_rule"], "style"].nunique() == P["styles_without_retail"]
    assert (v.loc[v["priced_by_rule"], "price"] * 100 % 100).round().eq(99).all()          # rule ends in .99
    assert len(issues(log, "start with http://")) == P["http_image_styles"]
    assert len(issues(log, "Stock given as")) == P["qty_text"]
    no_img = issues(log, "No images for")
    assert len(no_img) == P["styles_without_images"] + P["http_image_styles"]               # http-only styles end with none


def test_every_row_accounted_for_and_all_checks_pass(runs):
    first, _, _, _ = runs
    r = first["result"]
    assert r["overall"] == "PASS", r["checks"]
    fates = first["rows"]["fate"].value_counts()
    assert fates.sum() == first["kinds"]["product"]
    assert fates["imported"] == len(first["variants"]) == (first["shop"]["SKU"] != "").sum()


# --- the Shopify file ------------------------------------------------------------------------------------

def test_csv_matches_template_encoding_and_layout(runs):
    first, _, _, _ = runs
    data = first["csv"].read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and b"\r\n" not in data
    df = pd.read_csv(first["csv"], dtype=str, keep_default_na=False)
    assert list(df.columns) == TEMPLATE
    for handle, grp in df.groupby("URL handle", sort=False):
        assert grp.iloc[0]["Title"] != "" and (grp.iloc[1:]["Title"] == "").all()
        assert grp.iloc[0]["Status"] == "draft" and grp.iloc[0]["Vendor"] == "Harrow Peak"
        images_only = grp[grp["SKU"] == ""]
        assert (images_only["Product image URL"] != "").all()
        assert (images_only.drop(columns=["URL handle", "Product image URL", "Image position", "Image alt text"]) == "").all().all()
    assert "8.40" not in "".join(df["Variant Barcodes"])                                   # no scientific notation out


def test_checks_catch_broken_files(tmp_path, runs):
    first, _, _, _ = runs
    bad = first["shop"].copy()
    var = bad.index[bad["SKU"] != ""]
    bad.loc[var[1], "SKU"] = bad.loc[var[0], "SKU"]
    bad.loc[var[2], "Price"] = "1.00"
    bad.loc[var[2], "Cost per item"] = "9.00"
    bad.loc[0, "URL handle"] = "Bad Handle!"
    bad.loc[0, "Status"] = "live"
    path = write_csv(bad, tmp_path / "bad.csv")
    result = {name: res for name, res, _ in run_checks(bad, path)["checks"]}
    assert result["SKUs unique"] == "FAIL"
    assert result["Prices: numbers above zero, never below cost"] == "FAIL"
    assert result["Every product: valid handle, one title row"] == "FAIL"
    assert result["Allowed values: status, true/false, inventory, weight"] == "FAIL"


# --- next month's list -----------------------------------------------------------------------------------

def test_november_changes(runs):
    first, second, exp, _ = runs
    ch = second["changes"]
    store = first["variants"]
    changed = set(ch["price_changes"]["sku"])
    assert set(exp["retail_changed_singles"]) <= changed
    raised = set(store.loc[store["style"].isin(exp["raised_styles"]), "sku"])
    assert set(ch["cost_changes"]["sku"]) == raised
    assert len(ch["new_styles"]) == len(generate.NEW_IN_NOVEMBER)
    assert set(ch["archived_styles"]) == set(exp["dropped_styles"]) | {exp["discontinued_style"]}
    nv = ch["new_variants"]
    assert (nv["style"] == exp["new_color_style"]).sum() == exp["new_color_variants"]
    held_in_oct = set(first["rows"].loc[first["rows"]["fate"] == "held back", "sku"])
    assert set(nv["sku"]) - held_in_oct == set(nv.loc[nv["style"] == exp["new_color_style"], "sku"])


def test_november_update_files(runs):
    _, second, exp, tmp = runs
    files = second["files"]
    assert (files["new_products"]["SKU"] != "").sum() == exp["new_style_rows"]
    upd = files["update_existing"]
    v = second["variants"]
    for style in second["changes"]["touched_styles"]:
        handle_skus = set(upd.loc[upd["SKU"].str.startswith(style + "-"), "SKU"])
        assert set(v.loc[v["style"] == style, "sku"]) <= handle_skus                         # every variant listed
    arch = files["archive"]
    assert set(arch["Status"]) - {""} == {"archived"} and (arch["Status"] == "archived").sum() == 3
    assert (arch["Option1 value"] != "").all() and (arch["SKU"] != "").all()                 # Shopify needs the options
    assert (upd.groupby("URL handle")["Title"].apply(lambda s: (s != "").sum()) == 1).all()   # title on first row only
    for name in ("new_products", "update_existing", "archive"):
        df = pd.read_csv(tmp / "november" / f"{name}.csv", dtype=str, keep_default_na=False)
        assert all(c in TEMPLATE for c in df.columns)
