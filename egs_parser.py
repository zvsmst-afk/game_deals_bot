import aiohttp
import asyncio
from datetime import datetime, timedelta
import config
import database
import logging

logger = logging.getLogger(__name__)

class EGSParser:
    def __init__(self):
        self.endpoint = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"

    async def check_promotions(self):
        logger.info("Проверка EGS...")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.endpoint) as resp:
                    if resp.status != 200:
                        logger.error(f"EGS ответил с кодом {resp.status}")
                        return
                    data = await resp.json()
                    elements = data.get('data', {}).get('Catalog', {}).get('searchStore', {}).get('elements', [])
                    for game in elements:
                        promo = self._parse_game(game)
                        if promo:
                            promo_id = database.save_promotion(promo)
                            if promo_id and not promo.get('notified', False):
                                text = self._generate_post_text(promo)
                                database.save_draft(promo_id, text)
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
        original_price = fmt_price.get('originalPrice')
        discount_price = fmt_price.get('discountPrice')

        if original_price is None:
            return None

        is_free = (discount_price == '0' or discount_percent == 100)
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

        promo = {
            'store': 'egs',
            'app_id': game.get('id', ''),
            'title': title,
            'description': description[:200],
            'discount_percent': discount_percent,
            'old_price': int(original_price) if original_price else 0,
            'new_price': int(discount_price) if discount_price else 0,
            'currency': 'RUB',
            'start_date': start_date,
            'end_date': end_date,
            'region_restricted': False,
            'region_alternative': '',
            'url': url,
            'is_free': is_free
        }
        return promo

    def _generate_post_text(self, promo):
        if promo['is_free']:
            text = f"🎁 Раздача в EGS: {promo['title']}\n"
        else:
            text = f"🎮 {promo['title']} (EGS)\n"
        if promo['description']:
            text += f"📝 {promo['description'][:200]}...\n"
        if promo['is_free']:
            text += "🆓 Бесплатно\n"
        else:
            text += f"💰 Скидка: {promo['discount_percent']}% (было {promo['old_price']} → {promo['new_price']} {promo['currency']})\n"
        text += f"📅 Действует до {promo['end_date'][:10]}\n"
        text += "🌍 Доступна в РФ\n"
        text += f"🔗 [Ссылка в EGS]({promo['url']})"
        return text