import { logout } from './api'
import { useCurrentUser } from './AuthGate'
import { renderSegments } from './furigana'
import { ViewSettings } from './ViewSettings'
import { displayStyle, useViewSettings } from './useViewSettings'

// A line in the public-domain opening of 蜘蛛の糸 (Akutagawa), for judging the
// sizes and highlight against.
const SAMPLE = [
  { text: '或日', reading: 'あるひ' },
  { text: 'の事', reading: 'のこと' },
  { text: 'でございます。', reading: null },
]

export function SettingsPage() {
  const settings = useViewSettings()
  const user = useCurrentUser()
  return (
    <div className="new-document-form">
      <h1>Settings</h1>
      <h2>Account</h2>
      <p>Signed in as {user.name}</p>
      <button
        type="button"
        onClick={() => logout().then(() => window.location.reload())}
      >
        Log out
      </button>
      <h2>This device</h2>
      <p className="lyrics-box settings-sample" style={displayStyle(settings)}>
        <span className="token playing">{renderSegments(SAMPLE)}</span>
      </p>
      <ViewSettings />
    </div>
  )
}
