package fr.zukan.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// Mirrors of the server API (see /api/docs). Decimals arrive as strings.

@Serializable
data class ProvidersOut(
    @SerialName("local_login_enabled") val localLoginEnabled: Boolean,
    val providers: List<ProviderOut>,
)

@Serializable
data class ProviderOut(
    val name: String,
    @SerialName("display_name") val displayName: String,
    val issuer: String,
    @SerialName("mobile_client_id") val mobileClientId: String? = null,
    val scopes: List<String> = listOf("openid", "profile", "email"),
)

@Serializable
data class LoginIn(val username: String, val password: String, val mode: String = "token")

@Serializable
data class RefreshIn(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class OidcExchangeIn(
    @SerialName("id_token") val idToken: String,
    val nonce: String,
    @SerialName("access_token") val accessToken: String? = null,
)

@Serializable
data class TokenOut(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("expires_in") val expiresIn: Int,
)

@Serializable
data class MeOut(
    val id: Int,
    val username: String,
    val role: String,
    val language: String = "en",
    @SerialName("price_source") val priceSource: String = "cardmarket",
    // Shown price sources, main one first (servers before 0.7: only the main one).
    @SerialName("price_sources") val priceSources: List<String> = emptyList(),
) {
    val shownPriceSources get() = priceSources.ifEmpty { listOf(priceSource) }
}

/** Fields left null are not changed. */
@Serializable
data class SettingsIn(
    // Makes this source the main one.
    @SerialName("price_source") val priceSource: String? = null,
    @SerialName("price_sources") val priceSources: List<String>? = null,
)

@Serializable
data class PriceSourceOut(val id: String, val name: String, val currency: String)

@Serializable
data class ColorOut(val code: String, val name: String, val hex: String, val icon: String? = null)

@Serializable
data class FinishOut(val code: String, val name: String)

/** A rarity of the game (lowest first) and its pictogram, servers 0.10+. */
@Serializable
data class RarityOut(val code: String, val name: String, val icon: String? = null)

@Serializable
data class GameOut(
    val id: String,
    val name: String,
    val colors: List<ColorOut>,
    val finishes: List<FinishOut>,
    val languages: List<String>,
    @SerialName("has_prices") val hasPrices: Boolean,
    // Markets with prices, the game's main one first.
    @SerialName("price_sources") val priceSources: List<PriceSourceOut> = emptyList(),
    // Cardmarket URL segment ("Magic"), null when the game has no Cardmarket links.
    val cardmarket: String? = null,
    val rarities: List<RarityOut> = emptyList(),
)

@Serializable
data class OcrLineIn(
    val text: String,
    val left: Float? = null,
    val top: Float? = null,
    val width: Float? = null,
    val height: Float? = null,
)

@Serializable
data class IdentifyIn(val game: String?, val lines: List<OcrLineIn>)

@Serializable
data class HintsOut(
    val name: String? = null,
    @SerialName("set_code") val setCode: String? = null,
    @SerialName("collector_number") val collectorNumber: String? = null,
    val lang: String? = null,
)

@Serializable
data class CardRef(
    val id: Int,
    @SerialName("game_id") val gameId: String,
    val name: String,
    val colors: List<String>,
    // Latin name next to a non-Latin one ("ビードル (Aspicot)"), servers 0.6+.
    val translation: String? = null,
)

@Serializable
data class SetOut(
    val id: Int,
    val code: String,
    val name: String,
    val lang: String? = null,
    @SerialName("release_date") val releaseDate: String? = null,
)

@Serializable
data class PriceOut(
    val finish: String,
    val trend: String,
    val low: String? = null,
    val date: String,
    // Market (price source id) and its currency; the user's source comes first.
    val source: String = "cardmarket",
    val currency: String = "EUR",
)

/** A product page on a market. */
@Serializable
data class LinkOut(val source: String, val name: String, val url: String)

@Serializable
data class OwnedOut(
    @SerialName("item_id") val itemId: Int,
    val finish: String,
    val condition: String,
    val language: String,
    val quantity: Int,
)

@Serializable
data class PrintingOut(
    val id: Int,
    val set: SetOut,
    @SerialName("collector_number") val collectorNumber: String? = null,
    val rarity: String? = null,
    // The game's rarity (GameOut.rarities) for its pictogram, servers 0.10+.
    @SerialName("rarity_code") val rarityCode: String? = null,
    val finishes: List<String>,
    val languages: List<String>,
    val image: String? = null,
    // Back of double-faced cards.
    @SerialName("back_image") val backImage: String? = null,
    // "landscape": picture wider than tall (Riftbound battlefields), shown turned (0.10+).
    val orientation: String = "portrait",
    // Named as printed in its set, with a Latin translation of non-Latin names (servers 0.6+).
    val name: String = "",
    val translation: String? = null,
    val names: Map<String, String> = emptyMap(),
    val links: List<LinkOut> = emptyList(),
    val prices: List<PriceOut> = emptyList(),
    val owned: List<OwnedOut> = emptyList(),
)

@Serializable
data class CandidateOut(
    val score: Double,
    val match: String,
    val card: CardRef,
    // At most 30; `printingCount` tells how many the card has (search the others).
    val printings: List<PrintingOut>,
    @SerialName("printing_count") val printingCount: Int = printings.size,
)

@Serializable
data class IdentifyOut(
    @SerialName("game_id") val gameId: String? = null,
    val detected: HintsOut,
    val candidates: List<CandidateOut>,
    // The card was missing from the server catalog and was fetched from its source.
    val fetched: Boolean = false,
    // found, not_found (looks like a card, none matches), other_game (a card of
    // `detectedGame`, not of the chosen game; server 0.8) or not_a_card; "" before 0.7.
    val status: String = "",
    @SerialName("detected_game") val detectedGame: String? = null,
) {
    val notACard get() = status == "not_a_card"
    val otherGame get() = detectedGame?.takeIf { status == "other_game" }
}

@Serializable
data class AdjustIn(
    @SerialName("printing_id") val printingId: Int,
    val finish: String,
    val condition: String,
    val language: String,
    val delta: Int,
    val source: String = "scan",
)

@Serializable
data class ItemSetOut(val id: Int, val code: String, val name: String)

/** Market price trend over a period: direction up / down / flat, `change` 0.1 = +10 %. */
@Serializable
data class TrendOut(val direction: String, val change: Double = 0.0)

@Serializable
data class TrendsOut(val d1: TrendOut? = null, val d7: TrendOut? = null, val d30: TrendOut? = null)

@Serializable
data class ItemOut(
    val id: Int,
    val name: String,
    val translation: String? = null,
    val quantity: Int,
    val colors: List<String> = emptyList(),
    val rarity: String? = null,
    @SerialName("rarity_code") val rarityCode: String? = null,
    @SerialName("back_image") val backImage: String? = null,
    val orientation: String = "portrait",
    val trends: TrendsOut = TrendsOut(),
    @SerialName("printing_id") val printingId: Int = 0,
    @SerialName("card_id") val cardId: Int = 0,
    @SerialName("game_id") val gameId: String = "",
    val set: ItemSetOut? = null,
    @SerialName("collector_number") val collectorNumber: String? = null,
    val image: String? = null,
    val finish: String = "",
    val condition: String = "",
    val language: String = "",
    @SerialName("unit_price") val unitPrice: String? = null,
    val currency: String = "EUR",
    val total: String? = null,
)

@Serializable
data class ItemPageOut(val items: List<ItemOut>, val total: Int, val page: Int, @SerialName("page_size") val pageSize: Int)

@Serializable
data class GameValueOut(@SerialName("game_id") val gameId: String, val total: String, val quantity: Int, val currency: String = "EUR")

@Serializable
data class ValueOut(val currency: String = "EUR", val total: String, val quantity: Int, val games: List<GameValueOut> = emptyList())

@Serializable
data class AdjustOut(val item: ItemOut, @SerialName("transaction_id") val transactionId: Int)

@Serializable
data class CardSummaryOut(
    val id: Int,
    @SerialName("game_id") val gameId: String,
    val name: String,
    val translation: String? = null,
    val colors: List<String>,
    @SerialName("printing_count") val printingCount: Int,
    val image: String? = null,
    // Printing whose image is shown: the card opens on it (servers 0.6+).
    @SerialName("printing_id") val printingId: Int? = null,
    // Of that printing (servers 0.10+).
    @SerialName("back_image") val backImage: String? = null,
    val rarity: String? = null,
    @SerialName("rarity_code") val rarityCode: String? = null,
    val orientation: String = "portrait",
    @SerialName("price_min") val priceMin: String? = null,
    @SerialName("price_max") val priceMax: String? = null,
    val currency: String? = null,
)

@Serializable
data class CardPageOut(val items: List<CardSummaryOut>, val total: Int, val page: Int = 1)

@Serializable
data class CardOut(
    val id: Int,
    @SerialName("game_id") val gameId: String,
    val name: String,
    val translation: String? = null,
    val colors: List<String>,
    // Printing the catalog shows for the card (servers 0.6+).
    @SerialName("default_printing_id") val defaultPrintingId: Int? = null,
    val printings: List<PrintingOut>,
)

@Serializable
data class ErrorOut(val detail: kotlinx.serialization.json.JsonElement? = null)
