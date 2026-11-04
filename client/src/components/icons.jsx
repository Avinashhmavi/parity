// A few lucide icons under local names. Decorative unless a label is given.
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  ClipboardList,
  ExternalLink,
  History,
  Home,
  Info,
  RefreshCw,
  Search,
  Users,
  X
} from 'lucide-react'

const wrap =
  Icon =>
  ({ size = 18, ...rest }) => <Icon size={size} aria-hidden="true" focusable="false" {...rest} />

export const HomeIcon = wrap(Home)
export const JobsIcon = wrap(ClipboardList)
export const PeopleIcon = wrap(Users)
export const ProblemIcon = wrap(AlertTriangle)
export const HistoryIcon = wrap(History)
export const RefreshIcon = wrap(RefreshCw)
export const HelpIcon = wrap(CircleHelp)
export const SearchIcon = wrap(Search)
export const CloseIcon = wrap(X)
export const CheckIcon = wrap(Check)
export const ExternalIcon = wrap(ExternalLink)
export const PrevIcon = wrap(ChevronLeft)
export const NextIcon = wrap(ChevronRight)
export const InfoIcon = wrap(Info)
export const BackIcon = wrap(ArrowLeft)
