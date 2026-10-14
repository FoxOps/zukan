// A card name as the server shows it: non-Latin names come with a Latin translation,
// e.g. "ビードル (Aspicot)".
export function ShownName({ name, translation }: { name: string; translation?: string | null }) {
  return (
    <>
      {name}
      {translation && <span className="font-normal text-base-content/60"> ({translation})</span>}
    </>
  )
}
