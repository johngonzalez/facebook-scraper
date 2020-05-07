import re
import json

from requests_html import HTML

from .base_spider import BaseSpider
from .post_factory import PostFactory


class FacebookSpider(BaseSpider):
    name = "facebook_spider"
    base_url = "https://m.facebook.com/"

    _cursor_regex = re.compile(r'href:"(/page_content[^"]+)"')  # First request
    _cursor_regex_2 = re.compile(r'href":"(\\/page_content[^"]+)"')  # Other requests

    def __init__(self, page, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = [self.urljoin(self.base_url, f'/{page}/posts')]

    def parse(self, response):
        html = HTML(html=response.html.html.replace('<!--', '').replace('-->', ''))
        cursor_blob = html.html

        yield from self.extract_posts(html)

        next_page = self.get_next_page(cursor_blob)

        if next_page is not None:
            yield self.follow(response, next_page, callback=self.parse_see_more)

    def parse_see_more(self, response):
        data = json.loads(response.text.replace('for (;;);', '', 1))

        html = None
        cursor_blob = None

        for action in data['payload']['actions']:
            if action['cmd'] == 'replace':
                html = HTML(html=action['html'], url=self.base_url)
            elif action['cmd'] == 'script':
                cursor_blob = action['code']

        if html is not None:
            yield from self.extract_posts(html)

        if cursor_blob is not None:
            next_page = self.get_next_page(cursor_blob)

        if next_page is not None:
            yield self.follow(response, next_page, callback=self.parse_see_more)

    def extract_posts(self, node):
        for article in node.find('article'):
            yield PostFactory.make_item(article, self.base_url)

    def get_next_page(self, cursor_blob) -> str:
        match = self._cursor_regex.search(cursor_blob)
        if match:
            return match.groups()[0]

        match = self._cursor_regex_2.search(cursor_blob)
        if match:
            value = match.groups()[0]
            return value.encode('utf-8').decode('unicode_escape').replace('\\/', '/')

        return None
