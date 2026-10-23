"""Run three cached sample Publications with SQLite and live S2, then export."""
import json
import logging
from src.common.config import get_settings
from src.crawl.pipeline import run


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    settings = get_settings()
    print(json.dumps(run('data/crawl_hai', ['2412.08848', '2412.08849', '2412.08850'],
        settings.user_agent(), settings.s2_api_key), ensure_ascii=False))
