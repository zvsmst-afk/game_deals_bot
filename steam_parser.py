import aiohttp
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import config
import database
import logging
import os

logger = logging.getLogger(__name__)

class SteamParser:
    def __init__(self):
        self.api_url = "https://store.steampowered.com/api/appdetails"
        self.api_urls = [
            "https://store.steampowered.com/api/appdetails",
            "https://api.steampowered.com/api/appdetails",
        ]

    async def check_promotions(self):
        logger.info("Проверка Steam...")
        app_ids = self._get_discounted_apps()
        if not app_ids:
            logger.warning("Не удалось получить список игр со скидками")
            return
        for app_id in app_ids[:20]:
            try:
                promo = await self._get_promo_for_app(app_id)
                if promo:
                    promo_id = database.save_promotion(promo)
                    if promo_id and not promo.get('notified', False):
                        text = self._generate_post_text(promo)
                        database.save_draft(promo_id, text)
            except Exception as e:
                logger.error(f"Ошибка при обработке app_id {app_id}: {e}")
            await asyncio.sleep(0.5)
        logger.info("Проверка Steam завершена")

    async def _get_promo_for_app(self, app_id):
        """Получает данные об акции для одной игры"""
        # Сначала пробуем Россию
        data_ru = await self._fetch_app_details(app_id, config.PRIMARY_REGION)
        if data_ru and data_ru.get('success'):
            game_data = data_ru.get('data', {})
            price = game_data.get('price_overview', {})
            logger.info(f"✅ РОССИЯ: {game_data.get('name', '')} | Цена: {price.get('final')} {price.get('currency')} | Скидка: {price.get('discount_percent')}%")
            promo = self._analyze_data(app_id, data_ru, config.PRIMARY_REGION)
            if promo:
                return promo
        
        # Если в РФ нет, пробуем Казахстан
        data_kz = await self._fetch_app_details(app_id, config.FALLBACK_REGION)
        if data_kz and data_kz.get('success'):
            game_data = data_kz.get('data', {})
            price = game_data.get('price_overview', {})
            logger.info(f"✅ КАЗАХСТАН: {game_data.get('name', '')} | Цена: {price.get('final')} {price.get('currency')} | Скидка: {price.get('discount_percent')}%")
            promo = self._analyze_data(app_id, data_kz, config.FALLBACK_REGION)
            if promo:
                return promo
        
        return None

    def _get_discounted_apps(self):
        """Получает список игр со скидками"""
        url = "https://store.steampowered.com/search/?specials=1&category1=998"
        try:
            proxies = None
            if hasattr(config, 'PROXY') and config.PROXY:
                proxies = {'http': config.PROXY, 'https': config.PROXY}
            
            response = requests.get(url, timeout=30, proxies=proxies)
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.select('a.search_result_row')
            app_ids = []
            for link in links[:30]:
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
        """Запрашивает данные игры через Steam API"""
        params = {'appids': app_id, 'cc': cc, 'l': 'russian'}
        
        if hasattr(config, 'STEAM_API_KEY') and config.STEAM_API_KEY:
            params['key'] = config.STEAM_API_KEY

        proxy = config.PROXY if hasattr(config, 'PROXY') else None

        for url in self.api_urls:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        params=params,
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get(str(app_id))
            except Exception as e:
                logger.debug(f"Ошибка при запросе к {url}: {e}")
                continue
        return None

    def _get_russian_description(self, app_id):
        """Парсит страницу игры и возвращает русское описание"""
        url = f"https://store.steampowered.com/app/{app_id}/?l=russian"
        try:
            proxies = None
            if hasattr(config, 'PROXY') and config.PROXY:
                proxies = {'http': config.PROXY, 'https': config.PROXY}
            
            response = requests.get(url, timeout=10, proxies=proxies)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            desc_elem = soup.find('div', {'class': 'game_description_snippet'})
            if desc_elem:
                return desc_elem.text.strip()
            
            desc_elem = soup.find('div', {'class': 'game_area_description'})
            if desc_elem:
                return desc_elem.text.strip()
            
            return None
        except Exception as e:
            logger.debug(f"Ошибка парсинга страницы для {app_id}: {e}")
            return None

    def _analyze_data(self, app_id, data, region):
        """Анализирует данные игры и определяет акцию"""
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
        description = self._get_russian_description(app_id)
        if not description:
            description = game_data.get('short_description', '')
        
        old_price = price_overview.get('initial')
        new_price = price_overview.get('final')
        currency = price_overview.get('currency', 'RUB')

        # 🔥 БЕЗ КОНВЕРТАЦИИ — просто определяем доступность
        if region == config.PRIMARY_REGION:
            region_restricted = False
            region_alt = ''
        else:
            region_restricted = True
            region_alt = config.FALLBACK_REGION.upper()

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
            'region_alternative': region_alt,
            'url': url,
            'is_free': is_free
        }
        return promo

    def _generate_post_text(self, promo):
        """Генерирует текст поста"""
        currency_symbols = {
            'RUB': '₽',
            'KZT': '₸',
            'USD': '$',
            'EUR': '€',
        }
        symbol = currency_symbols.get(promo['currency'], promo['currency'])

        if promo['is_free']:
            text = f"🎁 Раздача: {promo['title']}\n"
        else:
            text = f"🎮 {promo['title']}\n"

        if promo['description']:
            text += f"📝 {promo['description'][:200]}...\n"

        if promo['is_free']:
            text += "🆓 Бесплатно\n"
        else:
            text += f"💰 Скидка: {promo['discount_percent']}% (было {promo['old_price']}{symbol} → {promo['new_price']}{symbol})\n"

        text += f"📅 Действует до {promo['end_date'][:10]}\n"

        if promo['region_restricted']:
            text += f"🌍 Цена в тенге (₸), можно забрать с {promo['region_alternative']}-аккаунта\n"
        else:
            text += "🌍 Доступна в РФ\n"

        text += f"🔗 [Ссылка в Steam]({promo['url']})"
        return text