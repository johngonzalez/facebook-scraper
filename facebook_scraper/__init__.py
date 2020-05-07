from .facebook_scraper import FacebookScraper

_default_scraper = FacebookScraper()


def get_posts(account):
    return _default_scraper.get_posts(account)
