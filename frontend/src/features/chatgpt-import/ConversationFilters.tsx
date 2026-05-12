import { useChatGptImportStore, type SortOption, type StatusFilter } from '../../core/store/chatGptImportStore'

// Native <select> ignores Tailwind styles on the open option list — the
// background and text colour have to be set inline on each <option> so
// the dropdown matches the app theme. See CLAUDE.md "Frontend styling
// gotchas → Native <select> dropdowns".
const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

export function ConversationFilters() {
  const titleSearch = useChatGptImportStore((s) => s.titleSearch)
  const sort = useChatGptImportStore((s) => s.sort)
  const statusFilter = useChatGptImportStore((s) => s.statusFilter)
  const setTitleSearch = useChatGptImportStore((s) => s.setTitleSearch)
  const setSort = useChatGptImportStore((s) => s.setSort)
  const setStatusFilter = useChatGptImportStore((s) => s.setStatusFilter)

  return (
    <div className="flex flex-wrap gap-3 mb-4">
      <input
        type="search"
        placeholder="Search title…"
        value={titleSearch}
        onChange={(e) => setTitleSearch(e.target.value)}
        className="flex-1 min-w-[200px] px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
      />
      <select
        value={sort}
        onChange={(e) => setSort(e.target.value as SortOption)}
        className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
      >
        <option value="create_time_desc" style={OPTION_STYLE}>Newest first</option>
        <option value="create_time_asc" style={OPTION_STYLE}>Oldest first</option>
        <option value="title_asc" style={OPTION_STYLE}>Title A–Z</option>
      </select>
      <select
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
        className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
      >
        <option value="all" style={OPTION_STYLE}>All</option>
        <option value="not_in_this_persona" style={OPTION_STYLE}>Not in this persona</option>
        <option value="not_in_any_persona" style={OPTION_STYLE}>Not in any persona</option>
        <option value="in_other_persona" style={OPTION_STYLE}>In another persona</option>
      </select>
    </div>
  )
}
