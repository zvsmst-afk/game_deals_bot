import aiohttp
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import config
import database
import logging
import re

logger = logging.getLogger(__name__)

class SteamParser:
    def __init__(self):
        self.api_url = "https://store.steampowered.com/api/appdetails"
        self.api_urls = [
            "https://store.steampowered.com/api/appdetails",
            "https://api.steampowered.com/api/appdetails",
        ]

    def _get_game_image(self, app_id):
        """Возвращает URL картинки игры (капсулы)"""
        return f"https://cdn.steamstatic.com/steam/apps/{app_id}/header.jpg"

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
                    if promo_id:
                        conn = database.get_db_connection()
                        cur = conn.cursor()
                        cur.execute('''
                            SELECT id FROM drafts 
                            WHERE promotion_id = ? AND status = 'pending'
                        ''', (promo_id,))
                        existing = cur.fetchone()
                        conn.close()
                        
                        if not existing:
                            text = self._generate_post_text(promo)
                            database.save_draft(promo_id, text)
                            logger.info(f"✅ Новый черновик: {promo['title']}")
                        else:
                            logger.info(f"⏩ Черновик для {promo['title']} уже существует, пропускаю")
            except Exception as e:
                logger.error(f"Ошибка при обработке app_id {app_id}: {e}")
            await asyncio.sleep(0.5)
        logger.info("Проверка Steam завершена")

    async def _get_promo_for_app(self, app_id):
        data_ru = await self._fetch_app_details(app_id, config.PRIMARY_REGION)
        if not data_ru or not data_ru.get('success'):
            return None
        
        game_data = data_ru.get('data', {})
        price_overview = game_data.get('price_overview')
        if not price_overview:
            return None

        discount = price_overview.get('discount_percent', 0)
        if discount == 0 and price_overview.get('final', 0) != 0:
            return None

        is_free = (price_overview.get('final', 0) == 0)
        title = game_data.get('name', 'Без названия')
        
        page_data = self._parse_steam_page(app_id)
        
        if page_data:
            old_price = page_data.get('old_price')
            new_price = page_data.get('new_price')
            currency = page_data.get('currency', 'RUB')
        else:
            old_price = price_overview.get('initial')
            new_price = price_overview.get('final')
            currency = price_overview.get('currency', 'RUB')

        region_restricted = False
        region_alt = ''

        end_date = (datetime.now() + timedelta(days=7)).isoformat()
        start_date = datetime.now().isoformat()
        url = f"https://store.steampowered.com/app/{app_id}/"

        promo = {
            'store': 'steam',
            'app_id': str(app_id),
            'title': title,
            'description': game_data.get('short_description', ''),
            'discount_percent': discount,
            'old_price': old_price,
            'new_price': new_price,
            'currency': currency,
            'start_date': start_date,
            'end_date': end_date,
            'region_restricted': region_restricted,
            'region_alternative': region_alt,
            'url': url,
            'is_free': is_free,
            'image_url': self._get_game_image(app_id)
        }
        return promo

    def _parse_steam_page(self, app_id):
        url = f"https://store.steampowered.com/app/{app_id}/?l=russian"
        try:
            proxies = None
            if hasattr(config, 'PROXY') and config.PROXY:
                proxies = {'http': config.PROXY, 'https': config.PROXY}
            
            response = requests.get(url, timeout=10, proxies=proxies)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            old_price_element = soup.find('div', {'class': 'discount_original_price'})
            if old_price_element:
                old_price_text = old_price_element.text.strip()
            else:
                old_price_text = None
            
            new_price_element = soup.find('div', {'class': 'discount_final_price'})
            if not new_price_element:
                new_price_element = soup.find('div', {'class': 'game_purchase_price'})
            
            if new_price_element:
                new_price_text = new_price_element.text.strip()
            else:
                new_price_text = None
            
            if not new_price_text:
                return None
            
            numbers_old = re.findall(r'[\d\s]+', old_price_text) if old_price_text else []
            numbers_new = re.findall(r'[\d\s]+', new_price_text) if new_price_text else []
            
            old_price = None
            new_price = None
            
            if numbers_old:
                old_price = int(''.join(numbers_old[0].split()))
            if numbers_new:
                new_price = int(''.join(numbers_new[0].split()))
            
            if old_price is None and new_price is not None:
                old_price = new_price
            
            if new_price is None:
                return None
            
            currency = 'RUB'
            if old_price_text and ('₸' in old_price_text or 'тенге' in old_price_text):
                currency = 'KZT'
            elif new_price_text and ('₸' in new_price_text or 'тенге' in new_price_text):
                currency = 'KZT'
            
            return {
                'old_price': old_price,
                'new_price': new_price,
                'currency': currency
            }
        except Exception as e:
            logger.debug(f"Ошибка парсинга страницы для {app_id}: {e}")
            return None

    def _get_discounted_apps(self):
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

    def _generate_post_text(self, promo):
        currency_symbols = {
            'RUB': '₽',
            'KZT': '₸',
            'USD': '$',
            'EUR': '€',
        }
        symbol = currency_symbols.get(promo['currency'], promo['currency'])

        if promo['is_free']:
            text = f"🎁 <b>РАЗДАЧА</b>\n"
            text += f"━━━━━━━━━━━━━━━━━━━━━\n"
            text += f"🎮 <b>{promo['title']}</b>\n\n"
        else:
            text = f"🔥 <b>СКИДКА</b>\n"
            text += f"━━━━━━━━━━━━━━━━━━━━━\n"
            text += f"🎮 <b>{promo['title']}</b>\n\n"

        if promo.get('description'):
            text += f"📝 {promo['description'][:250]}...\n\n"

        if promo['is_free']:
            text += f"💰 <b>Цена:</b> 🆓 БЕСПЛАТНО\n\n"
        else:
            text += f"💸 <b>Скидка:</b> {promo['discount_percent']}%\n"
            text += f"   🏷️ Было: <s>{promo['old_price']}{symbol}</s>\n"
            text += f"   ✅ Стало: <b>{promo['new_price']}{symbol}</b>\n\n"

        text += f"📅 <b>Действует до:</b> {promo['end_date'][:10]}\n\n"

        if promo['region_restricted']:
            text += f"🌍 Цена в тенге (₸), можно забрать с {promo['region_alternative']}-аккаунта\n\n"
        else:
            text += f"🌍 <b>Доступна в РФ</b>\n\n"

        # Ссылка в тексте убрана — она будет только в кнопке
        return text