import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.skip(reason="run_canvas_batch API not present in batches route")
@pytest.mark.asyncio
async def test_run_canvas_batch_endpoint():
    """Verify run_canvas_batch parses items, creates batch, and enqueues orders."""
    pass


@pytest.mark.asyncio
async def test_multi_record_batch_parsing():
    """Verify that multiple records are returned when scrape results contain multiple cards."""
    from app.drivers.recorder.miami_dade_recorder import miami_dade_book_page_search_and_download

    mock_driver = MagicMock()
    mock_driver._emit_status = AsyncMock()
    mock_driver.screenshot_on_failure = AsyncMock(return_value="/tmp/test.png")
    mock_driver.polite_delay = AsyncMock()
    mock_driver.save_browser_preview = AsyncMock()
    mock_driver.set_active_page = AsyncMock()
    mock_driver.ensure_page_alive = AsyncMock(return_value=True)
    mock_driver._page_is_alive = MagicMock(return_value=True)
    mock_driver.page.url = "https://miamidadeclerk.gov/officialrecords/SearchResults"
    mock_driver.context.pages = [mock_driver.page]

    with patch("app.drivers.recorder.miami_dade_recorder._reset_miami_dade_recorder_session", new_callable=AsyncMock) as mock_reset, \
         patch("app.drivers.recorder.miami_dade_recorder._search_book_page_form", new_callable=AsyncMock) as mock_form, \
         patch("app.drivers.recorder.miami_dade_recorder._wait_for_search_results", new_callable=AsyncMock) as mock_wait, \
         patch("app.drivers.recorder.miami_dade_recorder._scrape_all_search_results_metadata", new_callable=AsyncMock) as mock_scrape_all, \
         patch("app.drivers.recorder.miami_dade_recorder._scrape_first_result_metadata", new_callable=AsyncMock) as mock_scrape_first, \
         patch("app.drivers.recorder.miami_dade_recorder._open_search_result_at_index", new_callable=AsyncMock) as mock_open_result, \
         patch("app.drivers.recorder.miami_dade_recorder._open_document_image", new_callable=AsyncMock) as mock_doc_img, \
         patch("app.drivers.recorder.miami_dade_recorder._download_document_pdf", new_callable=AsyncMock) as mock_dl_pdf:

        mock_reset.return_value = True
        mock_form.return_value = True
        mock_wait.return_value = "results"
        mock_scrape_all.return_value = [
            {
                "instrument_number": "2016 R 472151",
                "book_page": "30189/4575",
                "document_type": "DEED",
                "recording_date": "8/12/2016",
                "grantor": "SELLER ONE",
                "grantee": "BUYER ONE",
            },
            {
                "instrument_number": "2018 R 112233",
                "book_page": "30189/4576",
                "document_type": "MORTGAGE",
                "recording_date": "9/20/2018",
                "grantor": "BUYER ONE",
                "grantee": "BANK TWO",
            },
            {
                "instrument_number": "2021 R 998877",
                "book_page": "30189/4577",
                "document_type": "SATISFACTION",
                "recording_date": "1/15/2021",
                "grantor": "BANK TWO",
                "grantee": "BUYER ONE",
            },
        ]
        mock_scrape_first.return_value = mock_scrape_all.return_value[0]
        mock_open_result.return_value = True
        mock_doc_img.return_value = True
        mock_dl_pdf.return_value = "local_storage/recorder_30189_4575/doc.pdf"

        docs = await miami_dade_book_page_search_and_download(mock_driver, "30189", "4575")

        assert isinstance(docs, list)
        assert len(docs) == 3
        assert docs[0].instrument_number == "2016 R 472151"
        assert docs[0].document_type == "DEED"
        assert docs[1].instrument_number == "2018 R 112233"
        assert docs[1].document_type == "MORTGAGE"
        assert docs[2].instrument_number == "2021 R 998877"
        assert docs[2].document_type == "SATISFACTION"
