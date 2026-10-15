package fr.zukan.app.data

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface ZukanApi {
    @GET("api/health")
    suspend fun health(): Map<String, String>

    @GET("api/auth/providers")
    suspend fun providers(): ProvidersOut

    @POST("api/auth/login")
    suspend fun login(@Body body: LoginIn): TokenOut

    @POST("api/auth/refresh")
    suspend fun refresh(@Body body: RefreshIn): TokenOut

    @POST("api/auth/logout")
    suspend fun logout(@Body body: RefreshIn)

    @POST("api/auth/oidc/{provider}/exchange")
    suspend fun exchange(@Path("provider") provider: String, @Body body: OidcExchangeIn): TokenOut

    @GET("api/auth/me")
    suspend fun me(): MeOut

    @PATCH("api/auth/me")
    suspend fun updateMe(@Body body: SettingsIn): MeOut

    @GET("api/games")
    suspend fun games(): List<GameOut>

    @POST("api/scan/identify")
    suspend fun identify(@Body body: IdentifyIn): IdentifyOut

    @POST("api/collection/adjust")
    suspend fun adjust(@Body body: AdjustIn): AdjustOut

    @POST("api/collection/transactions/{id}/undo")
    suspend fun undo(@Path("id") transactionId: Int): ItemOut

    @GET("api/cards")
    suspend fun searchCards(
        @Query("q") query: String?,
        @Query("game") game: String?,
        @Query("set_id") setId: Int? = null,
        @Query("color") colors: List<String>? = null,
        @Query("lang") lang: String? = null,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 30,
    ): CardPageOut

    @GET("api/games/{game}/sets")
    suspend fun sets(@Path("game") game: String): List<SetOut>

    @GET("api/collection")
    suspend fun collection(
        @Query("game") game: String? = null,
        @Query("q") query: String? = null,
        @Query("set_id") setId: Int? = null,
        @Query("condition") condition: String? = null,
        @Query("language") language: String? = null,
        @Query("sort") sort: String = "name",
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
    ): ItemPageOut

    @GET("api/collection/value")
    suspend fun collectionValue(): ValueOut

    @GET("api/cards/{id}")
    suspend fun card(@Path("id") cardId: Int): CardOut

    @GET("api/cards/{id}/printings")
    suspend fun printings(@Path("id") cardId: Int, @Query("q") query: String, @Query("limit") limit: Int = 50): List<PrintingOut>
}
