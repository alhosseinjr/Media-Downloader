def _fetch_info_sync(url):
    import requests
    response = requests.get(url)
    if response.status_code == 200:
        info = response.json()  # Assuming the response is in JSON format
        if isinstance(info, dict):
            return info  # We ensure it's a dictionary
        else:
            raise ValueError('Expected a dictionary from the response')
    else:
        raise ConnectionError(f'Failed to fetch info, status code: {response.status_code}')
