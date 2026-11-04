// A few lucide icons under local names, all decorative by default.
import {
  RefreshCw,
  Activity,
  Scale,
  ShieldAlert,
  Layers,
  Search,
  X,
  Check,
  AlertTriangle,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  Info
} from 'lucide-react'

const wrap =
  Icon =>
  ({ size = 16, ...rest }) => <Icon size={size} aria-hidden="true" focusable="false" {...rest} />

export const ArrowsClockwise = wrap(RefreshCw)
export const Pulse = wrap(Activity)
export const Scales = wrap(Scale)
export const ShieldWarning = wrap(ShieldAlert)
export const Stack = wrap(Layers)
export const MagnifyingGlass = wrap(Search)
export const Close = wrap(X)
export const CheckIcon = wrap(Check)
export const Warning = wrap(AlertTriangle)
export const External = wrap(ExternalLink)
export const Prev = wrap(ChevronLeft)
export const Next = wrap(ChevronRight)
export const Sort = wrap(ArrowUpDown)
export const InfoIcon = wrap(Info)
