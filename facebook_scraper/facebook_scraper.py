from requests_html import HTMLSession

from .facebook_spider import FacebookSpider


class FacebookScraper:
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/76.0.3809.87 Safari/537.36"
    )
    default_headers = {
        'User-Agent': user_agent,
        'Accept-Language': 'en-US,en;q=0.5',
        'cookie': 'locale=en_US;',
    }

    def __init__(self, session: HTMLSession = None, headers=None):
        if session is None:
            session = HTMLSession()
        self.session = session

        if headers is None:
            headers = self.default_headers
        self.session.headers.update(headers)

    def get_posts(self, account: str):
        return FacebookSpider(page=account).run(self.session)
