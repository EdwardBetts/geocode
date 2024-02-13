import pytest
import pytest_mock
import responses
from geocode.wikidata import APIResponseError, api_call


@responses.activate
def test_api_call_retries_on_failure(mocker: pytest_mock.plugin.MockerFixture) -> None:
    """Test retry for API calls."""
    # Patch 'time.sleep' to instantly return, effectively skipping the sleep
    mocked_sleep = mocker.patch("time.sleep", return_value=None)

    mock_send_mail = mocker.patch("geocode.mail.send_to_admin")

    responses.add(
        responses.GET,
        "https://www.wikidata.org/w/api.php",
        body="bad request",
        status=400,
    )
    with pytest.raises(APIResponseError):
        api_call({"action": "wbgetentities", "ids": "Q42"})
    assert len(responses.calls) == 5  # Assuming max_tries is 5

    assert mocked_sleep.call_count == 4

    mock_send_mail.assert_called()

    send_mail_call = mock_send_mail.call_args_list[0]
    assert send_mail_call[0] == (
        "Geocode error",
        "Error making Wikidata API call\n\nbad request",
    )
