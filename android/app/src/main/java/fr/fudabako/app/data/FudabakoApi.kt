package fr.fudabako.app.data

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface FudabakoApi {
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
        @Query("q") query: String,
        @Query("game") game: String?,
        @Query("page_size") pageSize: Int = 30,
    ): CardPageOut

    @GET("api/cards/{id}")
    suspend fun card(@Path("id") cardId: Int): CardOut
}
