class ItemFactory:
    @classmethod
    def make_item(cls):
        raise NotImplementedError

    @classmethod
    def find_and_search(cls, article, selector, pattern, cast=str):
        container = article.find(selector, first=True)
        match = container and pattern.search(container.html)

        return match and cast(match.groups()[0])

    @classmethod
    def parse_int(cls, value):
        return int(''.join(filter(lambda c: c.isdigit(), value)))
