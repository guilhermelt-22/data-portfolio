"""Everything that changes from one supplier or store to the next lives here, not in the code.

A new supplier usually means a few more column aliases and category rows; a new store means a different
vendor name, pricing rule or default status.
"""
from __future__ import annotations

VENDOR = "Harrow Peak"
SEASON_TAG = "FW26"
DEFAULT_STATUS = "draft"        # products arrive as drafts so the store owner reviews them before they go live
PUBLISHED = "true"
MARKUP = 2.0                    # used only when the supplier gives no retail price: wholesale x 2, ending in .99
WEIGHT_UNIT_DISPLAY = "g"

# Supplier header (lower case, trimmed) -> our column. One supplier calls it "Item #", the next "SKU".
COLUMN_ALIASES = {
    "sku": ["item #", "item#", "item no", "item number", "sku", "variant sku", "product code"],
    "style": ["style #", "style#", "style", "style no", "parent sku", "model"],
    "description": ["description", "item description", "product name", "name"],
    "color": ["colour", "color", "colorway"],
    "size": ["size", "sz"],
    "wholesale": ["wholesale", "wholesale price", "cost", "unit cost", "net price"],
    "retail": ["msrp", "retail", "rrp", "retail price", "srp"],
    "barcode": ["upc", "barcode", "ean", "gtin", "upc code"],
    "qty": ["avail.", "avail", "qty", "quantity", "stock", "on hand", "available"],
    "weight": ["wt", "weight", "unit weight"],
    "category": ["category", "cat", "product group"],
    "material": ["material", "fabric", "composition"],
    "features": ["features", "bullets", "key features"],
    "image1": ["img 1", "image 1", "image1", "main image"],
    "image2": ["img 2", "image 2", "image2"],
    "image3": ["img 3", "image 3", "image3"],
    "status": ["status", "item status", "lifecycle"],
}
REQUIRED = ["sku", "style", "description"]

# Supplier category code -> Shopify product type, and the Standard Product Taxonomy category as its ID.
# Shopify's import rejected the English breadcrumb path in a test import (13 Nov 2026) and accepted the IDs;
# the path is kept here only so a person can read what each ID means.
CATEGORIES = {
    "SOX": ("Socks", "aa-1-18", "Apparel & Accessories > Clothing > Socks"),
    "TEE": ("T-Shirts", "aa-1-13-8", "Apparel & Accessories > Clothing > Clothing Tops > T-Shirts"),
    "HOOD": ("Hoodies", "aa-1-13-13", "Apparel & Accessories > Clothing > Clothing Tops > Hoodies"),
    "BASE": ("Base Layers", "aa-1-1-2-4", "Apparel & Accessories > Clothing > Activewear > Activewear Tops > Base Layer Tops"),
    "HAT": ("Beanies", "aa-2-17-2", "Apparel & Accessories > Clothing Accessories > Hats > Beanies"),
    "GLV": ("Gloves", "aa-2-13", "Apparel & Accessories > Clothing Accessories > Gloves & Mittens"),
    "PACK": ("Backpacks", "lb-1", "Luggage & Bags > Backpacks"),
    "BTL": ("Water Bottles", "hg-11-3-11", "Home & Garden > Kitchen & Dining > Food & Beverage Carriers > Water Bottles"),
}

# Canonical size -> spellings seen in supplier files. The order of this dict is the display order.
SIZES = {
    "XS": ["XS", "X-SMALL", "XSMALL", "EXTRA SMALL"],
    "S": ["S", "SM", "SML", "SMALL"],
    "M": ["M", "MD", "MED", "MEDIUM"],
    "L": ["L", "LG", "LRG", "LARGE"],
    "XL": ["XL", "X-LARGE", "XLARGE", "EXTRA LARGE"],
    "XXL": ["XXL", "2XL", "XX-LARGE"],
    "One Size": ["OS", "O/S", "ONE SIZE", "ONESIZE"],
    "500 ml": ["500ML", "500 ML", "0.5L"],
    "750 ml": ["750ML", "750 ML", "0.75L"],
    "1 L": ["1L", "1 L", "1000ML", "1 LTR"],
    "20 L": ["20L", "20 L", "20 LTR"],
    "30 L": ["30L", "30 L", "30 LTR"],
}

COLORS = {
    "Black": ["BLACK", "BLK"],
    "Navy": ["NAVY", "NVY", "NAV"],
    "Charcoal": ["CHARCOAL", "CHAR", "CHR"],
    "Heather Grey": ["HEATHER GREY", "HEATHER GRAY", "HTHR GREY", "HTR GRY"],
    "Forest Green": ["FOREST GREEN", "FOREST", "FGRN", "FOR GRN"],
    "Olive": ["OLIVE", "OLV"],
    "Rust": ["RUST", "RST"],
    "Ochre": ["OCHRE", "OCH"],
    "Sand": ["SAND", "SND"],
    "Slate Blue": ["SLATE BLUE", "SLATE", "SLT BLU"],
    "White": ["WHITE", "WHT"],
    "Red": ["RED", "RD"],
}

DISCONTINUED = {"DISC", "DISC.", "DISCONTINUED", "INACTIVE", "EOL"}
