app_name = "apparel_erp"
app_title = "Apparel ERP"
app_publisher = "Your Company"
app_description = "Apparel PLM - Styles, Colour x Size matrix, auto SKU + BOM generation, Design & Tech Pack"
app_email = "admin@example.com"
app_license = "MIT"
app_version = "0.0.1"
required_apps = ["frappe"]

# Light navy/blue theming applied to standard desk forms (Style, Design Tech Pack, etc.)
app_include_css = "/assets/apparel_erp/css/apparel_theme.css"

# Doctype JS injected into forms
doctype_js = {
    "Style": "apparel_erp/product_development/doctype/style/style.js",
    "Design Tech Pack": "apparel_erp/product_development/doctype/design_tech_pack/design_tech_pack.js"
}

# Data records shipped with the app - installed/updated on `bench migrate`
fixtures = [
    {"doctype": "Print Format", "filters": [["name", "=", "Tech Pack Sheet"]]}
]
