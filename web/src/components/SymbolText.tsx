import type { Game } from '../api/queries'

// "{2}", "{W/U}", "{exhaust}": the tokens card texts use for symbols (`GameOut.symbols`).
const TOKEN = /(\{[^{}\s]{1,16}\})/

const SIZE = 'mx-px inline-block h-[1.15em] w-[1.15em] align-[-0.2em] object-contain'

/** Card text with the game's symbol tokens shown as pictograms; tokens the game does not
 * know (or whose picture is not downloaded yet) stay as written. */
export function SymbolText({ game, text }: { game?: Game; text: string }) {
  const symbols = game?.symbols ?? []
  if (symbols.length === 0 || !TOKEN.test(text)) return <>{text}</>
  return (
    <>
      {text.split(TOKEN).map((part, i) => {
        if (i % 2 === 0) return part
        const symbol = symbols.find((s) => s.token === part)
        if (!symbol?.icon) return part
        return <img key={i} src={symbol.icon} alt={part} title={symbol.name} className={SIZE} />
      })}
    </>
  )
}
