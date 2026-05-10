import openai
import os

def generate_answer(question_text, sku, openai_api_key):
    """
    Generates a draft answer to a customer's question using OpenAI.
    """
    if not openai_api_key:
        return "Не удалось сгенерировать ответ: нет ключа OpenAI API."

    try:
        client = openai.OpenAI(api_key=openai_api_key)

        prompt = f"""
Ты — менеджер магазина на Ozon. Твоя задача — вежливо, грамотно и по существу ответить на вопрос покупателя о товаре.
Покупатель задал вопрос по товару с SKU (или названием): {sku}
Вопрос покупателя: "{question_text}"

Сформулируй краткий, информативный ответ от лица магазина. Не придумывай характеристики, если не уверен. Если нужно, извинись за неудобства или поблагодари за интерес.
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful customer support agent for an Ozon store."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=250,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка при генерации ответа: {str(e)}"
