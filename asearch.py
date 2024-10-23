import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from bs4 import BeautifulSoup
from loguru import logger
from requests import HTTPError

MAX_PAGES = 50

def __response_hook(r, *args, **kwargs):
    try:
        r.raise_for_status()
    except HTTPError as e:
        raise HTTPError(
            BeautifulSoup(r.text).text.strip(), request=e.request, response=e.response
        ) from e

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/111.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3",
    }
)
session.hooks = {"response": __response_hook}

def get(url, **kwargs):
    return session.get(url, **kwargs)

@st.cache_data
def search(q: str):
    site = "amazon.it"
    url = f"https://{site}/s?k={q}"

    soup = BeautifulSoup(get(url).content, "html.parser")
    pages = int(soup.find_all("span", "s-pagination-item")[-1].text)

    if pages > MAX_PAGES:
        pages = MAX_PAGES

    def get_results(page: int):
        soup = BeautifulSoup(get(url, params={"page": page}).content, "html.parser")
        divs = soup.find_all("div", attrs={"data-component-type": "s-search-result"})

        if not divs:
            logger.error(f"No results found in HTML: {soup}")
            return None

        results = []
        for div in divs:
            try:
                result = {}
                asin = div["data-asin"]
                result["asin"] = asin
                result["img"] = div.find("img", "s-image")["src"]
                result["description"] = ": ".join(
                    h2.text.strip() for h2 in div.find_all("h2")
                )
                result["link"] = f"https://{site}/dp/{asin}"
                price = div.find("span", "a-price")
                if price:
                    result["price"] = price.find("span", "a-offscreen").text

                rating = div.find(
                    "span",
                    attrs={
                        "aria-label": lambda l: l
                        and re.fullmatch(".* su .* stelle", l)
                    },
                )
                if rating:
                    result["rating"] = float(rating["aria-label"].split(" ")[0].replace(",", "."))
                number_of_reviews = div.find(
                    "a", href=lambda h: h.endswith("#customerReviews")
                )
                if number_of_reviews:
                    result["number_of_reviews"] = int(
                        number_of_reviews.text.strip()
                        .replace(".", "")
                        .replace("(", "")
                        .replace(")", "")
                    )

                yield result
            except Exception as e:
                raise RuntimeError(f"Failed to process div: {div}") from e

        return results

    with ThreadPoolExecutor() as t:
        return [t for l in t.map(get_results, range(1, pages + 1)) for t in l]

st.title("ASearch")
st.subheader("Una ricerca migliore su Amazon")

term = st.text_input("Cerca")

if term:
    df = pd.DataFrame(search(term))
    df["price_value"] = df.price.str.replace("€", "").str.replace(".", "").str.replace(",", ".").astype(float)

    price_range = st.slider(
        "Prezzo",
        df.price_value.min(),
        df.price_value.max(),
        (df.price_value.min(), df.price_value.max()),
        format="€%.2f",
    )

    df_filtered = df[df.price_value.between(*price_range)]

    st.dataframe(
        df_filtered[
            ["link", "img", "description", "price_value", "number_of_reviews", "rating"]
        ],
        column_config={
            "link": st.column_config.LinkColumn("Link", display_text="Apri"),
            "img": st.column_config.ImageColumn("Immagine"),
            "description": "Descrizione",
            "price_value": st.column_config.NumberColumn("Prezzo", format="€%.2f"),
            "number_of_reviews": "Recensioni",
            "rating": st.column_config.NumberColumn("Valutazione", format="%.1f ⭐️"),
        },
        use_container_width=True,
    )

    st.plotly_chart(px.histogram(df_filtered.price_value))
