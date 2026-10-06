import { useState } from 'react'
import type { GlossSense } from './api'

// How many senses are listed before the expander.
const SENSE_LIMIT = 5

// A word's JMDict senses, each with its field and misc tags, as the gloss
// popup and the study reveal both show them.
export function SenseList({ senses }: { senses: GlossSense[] }) {
  const [expanded, setExpanded] = useState(false)

  if (senses.length === 0) {
    return <div className="gloss-senses-empty">No dictionary entry found.</div>
  }

  const shown = senses.slice(0, expanded ? undefined : SENSE_LIMIT)

  return (
    <>
      <ol className="gloss-senses">
        {shown.map((sense, i) => (
          <li key={`${sense.entry_idseq}-${i}`}>
            {sense.gloss.join('; ')}
            {(sense.field.length > 0 || sense.misc.length > 0) && (
              <span className="gloss-tag">
                {' '}
                ({[...sense.field, ...sense.misc].join(', ')})
              </span>
            )}
          </li>
        ))}
      </ol>
      {!expanded && senses.length > SENSE_LIMIT && (
        <button
          type="button"
          className="gloss-show-more"
          onClick={() => setExpanded(true)}
        >
          Show {senses.length - SENSE_LIMIT} more
        </button>
      )}
    </>
  )
}
