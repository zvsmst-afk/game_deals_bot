import aiohttp
import asyncio
from datetime import datetime, timedelta
import config
import database
import logging
import re

logger = logging.getLogger(__name__)

class EGSParser:
    def __init__(self):
        self.endpoint = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"

    async def check_promotions(self):
        logger.info("Проверка EGS...")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.endpoint, timeout=30) as resp:
                    if resp.status != 200:
                        logger.error(f"EGS ответил с кодом {resp.status}")
                        return
                    data = await resp.json()
                    elements = data.get('data', {}).get('Catalog', {}).get('searchStore', {}).get('elements', [])
                    for game in elements:
                        promo = self._parse_game(game)
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
                                    logger.info(f"✅ Новый черновик EGS: {promo['title']}")
                                else:
                                    logger.info(f"⏩ Черновик EGS для {promo['title']} уже существует, пропускаю")
                        await asyncio.sleep(0.2)
            except Exception as e:
                logger.error(f"Ошибка при запросе к EGS: {e}")
        logger.info("Проверка EGS завершена")

    def _parse_game(self, game):
        promotions = game.get('promotions', {})
        promotional_offers = promotions.get('promotionalOffers', [])
        if not promotional_offers:
            return None

        offer = promotional_offers[0]
        discount_setting = offer.get('discountSetting', {})
        discount_percent = discount_setting.get('discountPercentage', 0)

        price = game.get('price', {})
        total_price = price.get('totalPrice', {})
        fmt_price = total_price.get('fmtPrice', {})
        original_price_str = fmt_price.get('originalPrice')
        discount_price_str = fmt_price.get('discountPrice')

        if original_price_str is None:
            return None

        def parse_price(price_str):
            if not price_str:
                return 0
            cleaned = re.sub(r'[^\d.]', '', price_str)
            try:
                if '.' in cleaned:
                    return int(float(cleaned))
                else:
                    return int(cleaned)
            except ValueError:
                return 0

        original_price = parse_price(original_price_str)
        discount_price = parse_price(discount_price_str)

        is_free = (discount_price == 0 or discount_percent == 100)
        if not is_free and discount_percent == 0:
            return None

        title = game.get('title', 'Без названия')
        description = game.get('description', '')
        product_slug = game.get('productSlug')
        url = f"https://store.epicgames.com/ru/p/{product_slug}" if product_slug else "https://store.epicgames.com/"

        start_date_str = offer.get('startDate')
        end_date_str = offer.get('endDate')
        start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).isoformat() if start_date_str else datetime.now().isoformat()
        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).isoformat() if end_date_str else (datetime.now() + timedelta(days=7)).isoformat()

        currency = 'USD'
        if '$' in original_price_str:
            currency = 'USD'
        elif '€' in original_price_str:
            currency = 'EUR'
        elif '₽' in original_price_str:
            currency = 'RUB'
        elif '₸' in original_price_str:
            currency = 'KZT'

        promo = {
            'store': 'egs',
            'app_id': game.get('id', ''),
            'title': title,
            'description': description[:200],
            'discount_percent': discount_percent,
            'old_price': original_price,
            'new_price': discount_price,
            'currency': currency,
            'start_date': start_date,
            'end_date': end_date,
            'region_restricted': False,
            'region_alternative': '',
            'url': url,
            'is_free': is_free
        }
        return promo

    def _generate_post_text(self, promo):
        currency_symbols = {
            'RUB': '₽',
            'KZT': '₸',
            'USD': '$',
            'EUR': '€',
        }
        symbol = currency_symbols.get(promo['currency'], promo['currency'])

        if promo['is_free']:
            text = f"🎁 <b>РАЗДАЧА В EGS</b>\n"
            text += f"━━━━━━━━━━━━━━━━━━━━━\n"
            text += f"🎮 <b>{promo['title']}</b>\n\n"
        else:
            text = f"🔥 <b>СКИДКА В EGS</b>\n"
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
        text += f"🌍 <b>Доступна в РФ</b>\n\n"

        text += f"🔗 <a href='{promo['url']}'>Перейти в EGS</a>"
        return text