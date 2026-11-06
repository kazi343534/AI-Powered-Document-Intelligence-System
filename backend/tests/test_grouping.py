"""Tests for multi-page invoice grouping logic."""

from app.parsers.grouping import group_invoice_pages


class _Page:
    def __init__(self, page_number: int, text: str):
        self.page_number = page_number
        self.text = text


def _pages(pairs):
    return [_page for _page in pairs]


def test_single_page_one_group():
    pages = [_Page(1, "INVOICE\nInvoice No: INV-1\nSupplier: ACME LTD")]
    groups = group_invoice_pages(pages)
    assert len(groups) == 1
    assert groups[0].page_start == 1
    assert groups[0].page_end == 1
    assert groups[0].invoice_number == "1"


def test_continuation_page_joins_current_group():
    pages = [
        _Page(1, "INVOICE\nInvoice No: INV-2\nSupplier: ACME LTD"),
        _Page(2, "continuation page with more items"),
        _Page(3, "more continuation text"),
    ]
    groups = group_invoice_pages(pages)
    assert len(groups) == 1
    assert groups[0].page_start == 1
    assert groups[0].page_end == 3


def test_new_invoice_number_starts_new_group():
    pages = [
        _Page(1, "INVOICE\nInvoice No: INV-3\nSupplier: ACME LTD"),
        _Page(2, "INVOICE\nInvoice No: INV-4\nSupplier: ACME LTD"),
    ]
    groups = group_invoice_pages(pages)
    assert len(groups) == 2
    assert groups[0].invoice_number == "3"
    assert groups[0].page_end == 1
    assert groups[1].invoice_number == "4"
    assert groups[1].page_start == 2


def test_no_number_everywhere_single_group():
    pages = [_Page(1, "some random text"), _Page(2, "more random text")]
    groups = group_invoice_pages(pages)
    assert len(groups) == 1
    assert groups[0].invoice_number is None
    assert groups[0].page_end == 2


def test_confidence_bounds():
    pages = [_Page(1, "INVOICE\nInvoice No: INV-5\nSupplier: ACME LTD")]
    groups = group_invoice_pages(pages)
    assert 0.0 <= groups[0].confidence <= 1.0
    assert groups[0].confidence > 0.9


def test_record_headings_split_invoices_within_one_page():
    page = _Page(
        1,
        "\n".join(
            [
                "COMMERCIAL TAX INVOICE — RECORD 01",
                "Invoice Number",
                "INV-2026-00101",
                "Supplier Name",
                "Apex Cloud Infrastructure Ltd.",
                "Subtotal (USD)",
                "100.00",
                "Total Amount Due (USD)",
                "110.00",
                "COMMERCIAL TAX INVOICE — RECORD 02",
                "Invoice Number",
                "INV-2026-00102",
                "Supplier Name",
                "Vanguard Office Furnishings Co.",
                "Total Amount Due (USD)",
                "220.00",
            ]
        ),
    )
    groups = group_invoice_pages([page])
    assert len(groups) == 2
    assert groups[0].page_start == groups[1].page_start == 1
    assert groups[0].invoice_number == "202600101"
    assert groups[1].invoice_number == "202600102"
    assert "INV-2026-00101" in groups[0].page_texts[0][1]
    assert "INV-2026-00102" not in groups[0].page_texts[0][1]
    assert "INV-2026-00102" in groups[1].page_texts[0][1]


def test_inline_invoice_numbers_split_the_same_page():
    page = _Page(
        1,
        "\n".join(
            [
                "INVOICE",
                "Invoice No: INV-100",
                "Supplier: ACME LTD",
                "Total 10.00",
                "INVOICE",
                "Invoice No: INV-200",
                "Supplier: BETA LTD",
                "Total 20.00",
            ]
        ),
    )
    groups = group_invoice_pages([page])
    assert len(groups) == 2
    assert groups[0].invoice_number == "100"
    assert groups[1].invoice_number == "200"
    assert "INV-100" in groups[0].page_texts[0][1]
    assert "INV-200" not in groups[0].page_texts[0][1]
    assert "INV-200" in groups[1].page_texts[0][1]


def test_record_headings_split_pages_into_separate_invoices():
    pages = [
        _Page(
            1,
            "TAX INVOICE — RECORD 01\nInvoice Number\nINV-1\n"
            "Supplier Name\nApex Ltd.\nTotal Amount Due\n10.00",
        ),
        _Page(
            2,
            "TAX INVOICE — RECORD 02\nInvoice Number\nINV-2\n"
            "Supplier Name\nBeta Ltd.\nTotal Amount Due\n20.00",
        ),
    ]
    groups = group_invoice_pages(pages)
    assert len(groups) == 2
    assert (groups[0].page_start, groups[0].page_end) == (1, 1)
    assert (groups[1].page_start, groups[1].page_end) == (2, 2)
    assert groups[0].invoice_number == "1"
    assert groups[1].invoice_number == "2"


def test_empty_input():
    assert group_invoice_pages([]) == []
