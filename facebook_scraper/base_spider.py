from collections import deque
from urllib.parse import urljoin


# TODO: Add HTTP method
class Request:
    def __init__(self, url, callback):
        self.url = url
        self.callback = callback


class BaseSpider:
    start_urls = []

    def start_requests(self):
        for url in self.start_urls:
            yield self.make_request(url, callback=self.parse)

    def run(self, session):
        queue = deque(self.start_requests())

        while queue:
            request = queue.popleft()
            response = session.get(request.url)

            for item in request.callback(response):
                if isinstance(item, Request):
                    queue.append(item)
                else:
                    yield item

    def parse(self, response):
        raise NotImplementedError

    def make_request(self, *args, **kwargs):
        return Request(*args, **kwargs)

    def follow(self, response, url, callback):
        url = self.urljoin(response.url, url)
        return self.make_request(url, callback=callback)

    def urljoin(self, base, url):
        return urljoin(base, url)
