# kotlinx.serialization keeps generated serializers of @Serializable classes.
-keepattributes *Annotation*, InnerClasses
-keep,includedescriptorclasses class fr.zukan.app.**$$serializer { *; }
-keepclassmembers class fr.zukan.app.** {
    *** Companion;
}
-keepclasseswithmembers class fr.zukan.app.** {
    kotlinx.serialization.KSerializer serializer(...);
}
# Retrofit interfaces are used through reflection.
-keep,allowobfuscation interface fr.zukan.app.data.ZukanApi
# ML Kit (via firebase-components) instantiates registrars listed in the manifest by reflection;
# R8 full mode drops their unused no-arg constructors, leaving ML Kit uninitialized.
-keep class * implements com.google.firebase.components.ComponentRegistrar { <init>(); }
