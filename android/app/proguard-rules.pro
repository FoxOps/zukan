# kotlinx.serialization keeps generated serializers of @Serializable classes.
-keepattributes *Annotation*, InnerClasses
-keep,includedescriptorclasses class fr.fudabako.app.**$$serializer { *; }
-keepclassmembers class fr.fudabako.app.** {
    *** Companion;
}
-keepclasseswithmembers class fr.fudabako.app.** {
    kotlinx.serialization.KSerializer serializer(...);
}
# Retrofit interfaces are used through reflection.
-keep,allowobfuscation interface fr.fudabako.app.data.FudabakoApi
