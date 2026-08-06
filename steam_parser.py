import aiohttp
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import config
import database
import logging

logger = logging.getLogger(__name__)

class SteamParser:
    def __init__(self):
        self.api_url = "https://store.steampowered.com/api/appdetails"

    async def check_promotions(self):
        logger.info("Проверка Steam...")
        app_ids = self._get_discounted_apps()
        if not app_ids:
            logger.warning("Не удалось получить список игр со скидками")
            return
        for app_id in app_ids[:100]:
            try:
                data_ru = await self._fetch_app_details(app_id, config.PRIMARY_REGION)
                data_kz = await self._fetch_app_details(app_id, config.FALLBACK_REGION)
                promo = self._analyze_data(app_id, data_ru, data_kz)
                if promo:
                    promo_id = database.save_promotion(promo)
                    if promo_id and not promo.get('notified', False):
                        text = self._generate_post_text(promo)
                        database.save_draft(promo_id, text)
            except Exception as e:
                logger.error(f"Ошибка при обработке app_id {app_id}: {e}")
            await asyncio.sleep(0.3)
        logger.info("Проверка Steam завершена")

    def _get_discounted_apps(self):
        url = "https://store.steampowered.com/search/?specials=1&category1=998"
        try:
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.select('a.search_result_row')
            app_ids = []
            for link in links:
                href = link.get('href')
                if href and 'app/' in href:
                    parts = href.split('/')
                    for part in parts:
                        if part.isdigit():
                            app_ids.append(int(part))
                            break
            return app_ids
        except Exception as e:
            logger.error(f"Ошибка парсинга страницы скидок Steam: {e}")
            return []

    async def _fetch_app_details(self, app_id, cc):
        params = {'appids': app_id, 'cc': cc}
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get(str(app_id))
        return None

    def _analyze_data(self, app_id, data_ru, data_kz):
        if not data_ru or not data_ru.get('success'):
            if data_kz and data_kz.get('success'):
                region_restricted = True
                region_alt = config.FALLBACK_REGION.upper()
                data = data_kz
            else:
                return None
        else:
            region_restricted = False
            region_alt = None
            data = data_ru

        game_data = data.get('data')
        if not game_data:
            return None

        price_overview = game_data.get('price_overview')
        if not price_overview:
            return None

        discount = price_overview.get('discount_percent', 0)
        if discount == 0 and price_overview.get('final', 0) != 0:
            return None

        is_free = (price_overview.get('final', 0) == 0)

        title = game_data.get('name', 'Без названия')
        description = game_data.get('short_description', '')
        old_price = price_overview.get('initial')
        new_price = price_overview.get('final')
        currency = price_overview.get('currency', 'RUB')
        end_date = (datetime.now() + timedelta(days=7)).isoformat()
        start_date = datetime.now().isoformat()
        url = f"https://store.steampowered.com/app/{app_id}/"

        promo = {
            'store': 'steam',
            'app_id': str(app_id),
            'title': title,
            'description': description,
            'discount_percent': discount,
            'old_price': old_price,
            'new_price': new_price,
            'currency': currency,
            'start_date': start_date,
            'end_date': end_date,
            'region_restricted': region_restricted,
            'region_alternative': region_alt if region_alt else '',
            'url': url,
            'is_free': is_free
        }
        return promo

    def _generate_post_text(self, promo):
        if promo['is_free']:
            text = f"🎁 Раздача: {promo['title']}\n"
        else:
            text = f"🎮 {promo['title']}\n"
        if promo['description']:
            text += f"📝 {promo['description'][:200]}...\n"
        if promo['is_free']:
            text += "🆓 Бесплатно\n"
        else:
            text += f"💰 Скидка: {promo['discount_percent']}% (было {promo['old_price']} → {promo['new_price']} {promo['currency']})\n"
        text += f"📅 Действует до {promo['end_date'][:10]}\n"
        if promo['region_restricted']:
            text += f"🌍 Для РФ недоступна, можно забрать с {promo['region_alternative']}-аккаунта\n"
        else:
            text += "🌍 Доступна в РФ\n"
        text += f"🔗 [Ссылка в Steam]({promo['url']})"
        return text