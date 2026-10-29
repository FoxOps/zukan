'use strict';
(() => {
  const supported = ['en', 'fr', 'de', 'es'];
  const languageSelect = document.getElementById('language');
  const metadata = {
    en: {title: 'Zukan — A home for every card.', description: 'Your trading card collection, on your own terms. Discover Zukan, a self-hosted collection manager with an Android scanner, six games and market price tracking.', navigation: 'Main navigation', language: 'Language', home: 'Zukan — Home', screenshot: 'Zukan web interface: collection grid in the dark theme, with card images, quantities, conditions and market prices.'},
    fr: {title: 'Zukan — Vos cartes ont trouvé leur place.', description: 'Votre collection de cartes, à votre façon. Découvrez Zukan : un gestionnaire auto-hébergé avec scanner Android, six jeux et suivi des prix du marché.', navigation: 'Navigation principale', language: 'Langue', home: 'Zukan — Accueil', screenshot: 'Interface web de Zukan : collection en thème sombre, avec visuels des cartes, quantités, états et prix du marché.'},
    de: {title: 'Zukan — Ein Zuhause für jede Karte.', description: 'Deine Sammelkartensammlung auf deinem eigenen Server. Zukan bietet einen Android-Scanner, sechs Spiele und die Verfolgung von Marktpreisen.', navigation: 'Hauptnavigation', language: 'Sprache', home: 'Zukan — Startseite', screenshot: 'Zukan-Weboberfläche: Sammlung im dunklen Design mit Kartenbildern, Mengen, Zuständen und Marktpreisen.'},
    es: {title: 'Zukan — Un hogar para cada carta.', description: 'Tu colección de cartas en tu propio servidor. Descubre Zukan, con escáner Android, seis juegos y seguimiento de precios del mercado.', navigation: 'Navegación principal', language: 'Idioma', home: 'Zukan — Inicio', screenshot: 'Interfaz web de Zukan: colección con tema oscuro, imágenes de cartas, cantidades, estados y precios del mercado.'}
  };
  function setLanguage(language, remember = false) {
    if (!supported.includes(language)) language = 'en';
    document.documentElement.lang = language;
    document.querySelectorAll('[data-en]').forEach(element => {
      element.textContent = element.dataset[language] || element.dataset.en;
    });
    const text = metadata[language];
    languageSelect.value = language;
    languageSelect.setAttribute('aria-label', text.language);
    document.querySelector('nav').setAttribute('aria-label', text.navigation);
    document.querySelectorAll('a[aria-label^="Zukan —"]').forEach(link => link.setAttribute('aria-label', text.home));
    document.querySelector('.product-screenshot img').alt = text.screenshot;
    const androidAlt = {
      en: 'Zukan Android application: collection view in the dark theme with estimated value, game filters and card quantities.',
      fr: 'Application Android de Zukan : collection en thème sombre avec valeur estimée, filtres par jeu et quantités des cartes.',
      de: 'Zukan-Android-App: Sammlung im dunklen Design mit geschätztem Wert, Spielfiltern und Kartenmengen.',
      es: 'Aplicación Android de Zukan: colección con tema oscuro, valor estimado, filtros por juego y cantidades de cartas.'
    };
    document.querySelector('.android-screenshot img').alt = androidAlt[language];
    document.title = text.title;
    document.querySelector('meta[name="description"]').content = text.description;
    document.querySelector('meta[property="og:title"]').content = text.title;
    document.querySelector('meta[property="og:description"]').content = text.description;
    if (remember) {
      try { localStorage.setItem('zukan-page-language', language); } catch { /* Language selection also works without storage. */ }
    }
  }
  // Regional variants use their base language (de-DE -> de). Unsupported languages use English.
  const browserLanguage = (navigator.language || 'en').toLowerCase().split(/[-_]/)[0];
  let initialLanguage = supported.includes(browserLanguage) ? browserLanguage : 'en';
  try {
    const saved = localStorage.getItem('zukan-page-language');
    if (supported.includes(saved)) initialLanguage = saved;
  } catch { /* Use the browser language if storage is unavailable. */ }
  setLanguage(initialLanguage);
  languageSelect.addEventListener('change', () => setLanguage(languageSelect.value, true));
})();
