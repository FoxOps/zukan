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
# ML Kit (via firebase-components) instantiates registrars listed in the manifest by reflection;
# R8 full mode drops their unused no-arg constructors, leaving ML Kit uninitialized.
-keep class * implements com.google.firebase.components.ComponentRegistrar { <init>(); }
