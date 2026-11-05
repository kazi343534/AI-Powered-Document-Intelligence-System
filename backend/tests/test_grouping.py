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


def test_empty_input():
    assert group_invoice_pages([]) == []
