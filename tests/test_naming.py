from naming import (
    product_name, material, color_from_handle, build_alt, build_filename,
    is_standard_filename, is_standard_alt, normalize_view, basename_from_url,
)


def test_product_name_and_material():
    assert product_name("Herve Sweater in Cashmere") == "Herve Sweater"
    assert material("Herve Sweater in Cashmere") == "Cashmere"
    assert product_name("Brontë Jean in Rigid Denim") == "Brontë Jean"
    assert material("E-gift Card") == ""


def test_color_from_handle():
    assert color_from_handle("herve-sweater-black", "Herve Sweater in Cashmere") == "Black"
    assert color_from_handle("adrian-shirt-wine-tartan", "Adrian Shirt in Cotton") == "Wine Tartan"
    assert color_from_handle("bronte-jean-subdued-indigo", "Brontë Jean in Rigid Denim") == "Subdued Indigo"
    assert color_from_handle("gide-sweater-in-wool-plum", "Gide Sweater in Wool") == "Plum"


def test_build_alt():
    alt = build_alt("Alune Dress in Wool Silk", "Citron", "Ghost Front")
    assert alt == "AFLALO Alune Dress in Wool Silk – Citron - Ghost Front"
    assert is_standard_alt(alt)
    assert not is_standard_alt("Alune Dress in Wool Silk - AFLALO")
    assert len(build_alt("X" * 200, "Citron", "Ghost Front")) <= 125


def test_build_filename_and_standard_check():
    fn = build_filename("Herve Sweater in Cashmere", "Black", "Model Front", 1, "webp")
    assert fn == "HerveSweater_Black_ModelFront_01.webp"
    assert is_standard_filename(fn)
    fn2 = build_filename("Brontë Jean in Rigid Denim", "", "Ghost Back", 12, "JPEG")
    assert fn2 == "BronteJean_GhostBack_12.jpg"
    assert is_standard_filename(fn2)
    assert not is_standard_filename("250812_JI_AFLALO_SHOT_07_092_4511e199.webp")
    assert not is_standard_filename("AdrianShirt_WineTartan_FRONT_1.webp")


def test_normalize_view():
    assert normalize_view("Model Back") == "Model Back"
    assert normalize_view("this is a ghost mannequin shot from the back") == "Ghost Back"
    assert normalize_view("close-up of the fabric texture") == "Detail"
    assert normalize_view("garbage") == "Model Front"


def test_basename_from_url():
    assert basename_from_url("https://cdn.shopify.com/s/files/1/x/files/Foo_01.webp?v=123") == "Foo_01.webp"
