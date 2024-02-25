import pytest
import pytest_mock
import requests
import responses
from geocode.wikidata import APIResponseError, QueryError, api_call, wdqs

max_tries = 5


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
    assert len(responses.calls) == max_tries

    assert mocked_sleep.call_count == max_tries - 1

    mock_send_mail.assert_called()

    send_mail_call = mock_send_mail.call_args_list[0]
    assert send_mail_call[0] == (
        "Geocode error",
        "Error making Wikidata API call\n\nbad request",
    )


def test_api_call_retries_on_connection_error(
    mocker: pytest_mock.plugin.MockerFixture,
) -> None:
    """Test retry for API calls on connection error."""
    # Patch 'time.sleep' to instantly return, effectively skipping the sleep
    mocked_sleep = mocker.patch("time.sleep", return_value=None)

    # Patch 'requests.get' to raise a ConnectionError
    mocker.patch("requests.get", side_effect=requests.exceptions.ConnectionError)
    mocker.patch("geocode.mail.send_to_admin")

    with pytest.raises(requests.exceptions.ConnectionError):
        api_call({"action": "wbgetentities", "ids": "Q42"})

    assert mocked_sleep.call_count == max_tries - 1


def test_wdqs_retry(mocker: pytest_mock.plugin.MockerFixture) -> None:
    """Test retry for WDQS API calls."""
    # Patch 'time.sleep' to instantly return, effectively skipping the sleep
    mocked_sleep = mocker.patch("time.sleep", return_value=None)

    responses.add(
        responses.POST,
        "https://query.wikidata.org/bigdata/namespace/wdq/sparql",
        body="bad request",
        status=400,
    )

    with pytest.raises(QueryError):
        wdqs("test query")

    max_tries = 5
    assert mocked_sleep.call_count == max_tries - 1
