package fr.fudabako.app.data

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
)

/** Fields left null are not changed. */
@Serializable
data class SettingsIn(@SerialName("price_source") val priceSource: String? = null)

@Serializable
data class PriceSourceOut(val id: String, val name: String, val currency: String)

@Serializable
data class ColorOut(val code: String, val name: String, val hex: String, val icon: String? = null)

@Serializable
data class FinishOut(val code: String, val name: String)

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
data class CardRef(val id: Int, @SerialName("game_id") val gameId: String, val name: String, val colors: List<String>)

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
    val finishes: List<String>,
    val languages: List<String>,
    val image: String? = null,
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
)

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

@Serializable
data class ItemOut(
    val id: Int,
    val name: String,
    val quantity: Int,
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
    val colors: List<String>,
    @SerialName("printing_count") val printingCount: Int,
    val image: String? = null,
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
    val colors: List<String>,
    val printings: List<PrintingOut>,
)

@Serializable
data class ErrorOut(val detail: kotlinx.serialization.json.JsonElement? = null)
