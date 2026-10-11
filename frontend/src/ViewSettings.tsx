import type { ViewSettingsState } from './useViewSettings'

// The controls for `settings`. `display` is text size and furigana size and
// the highlight; `furigana` is the furigana size within it; `nudge` is the
// timing editor's nudge step. Seek step is always shown.
export function ViewSettings({
  settings,
  display = true,
  furigana = true,
  nudge = true,
}: {
  settings: ViewSettingsState
  display?: boolean
  furigana?: boolean
  nudge?: boolean
}) {
  const { highlight } = settings
  return (
    <div className="text-size-controls">
      {display && (
        <RangeControl
          id="font-size"
          label="Text size"
          unit="px"
          value={settings.fontSize}
          onChange={settings.setFontSize}
          min={14}
          max={32}
        />
      )}
      {display && furigana && (
        <RangeControl
          id="furigana-size"
          label="Furigana size"
          unit="px"
          value={settings.furiganaSize}
          onChange={settings.setFuriganaSize}
          min={6}
          max={20}
        />
      )}
      <RangeControl
        id="seek-seconds"
        label="Seek step"
        unit="s"
        value={settings.seekSeconds}
        onChange={settings.setSeekSeconds}
        min={1}
        max={30}
        hint={
          <>
            (<kbd>,</kbd> / <kbd>.</kbd>)
          </>
        }
      />
      {nudge && (
        <RangeControl
          id="nudge-ms"
          // Not "Nudge step": with its keys, that won't fit the label
          // column.
          label="Nudge"
          unit="ms"
          value={settings.nudgeMs}
          onChange={settings.setNudgeMs}
          min={10}
          max={500}
          step={10}
          hint={
            <>
              (<kbd>←</kbd>
              <kbd>→</kbd>)
            </>
          }
        />
      )}
      {display && (
        <>
          <div className="control">
            <label htmlFor="highlight-color">Highlight color</label>
            <input
              id="highlight-color"
              type="color"
              value={highlight.color}
              onChange={(e) => highlight.setColor(e.target.value)}
            />
          </div>
          <RangeControl
            id="highlight-opacity"
            label="Highlight opacity"
            unit="%"
            value={highlight.opacity}
            onChange={highlight.setOpacity}
            min={5}
            max={100}
          />
        </>
      )}
    </div>
  )
}

function RangeControl({
  id,
  label,
  unit,
  value,
  onChange,
  min,
  max,
  step,
  hint,
}: {
  id: string
  label: string
  unit: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
  step?: number
  // Shown after the value, e.g. the keys that use the setting.
  hint?: React.ReactNode
}) {
  return (
    <div className="control">
      <label htmlFor={id}>
        {label} {value}
        {unit}
        {hint && <> {hint}</>}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  )
}
