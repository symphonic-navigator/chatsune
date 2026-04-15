import ReactMarkdown from 'react-markdown'
import { Sheet } from './Sheet'
import type { DeletionReportDto } from '../types/deletion'

interface DeletionReportSheetProps {
  report: DeletionReportDto | null
  onClose: () => void
}

const TARGET_LABEL: Record<DeletionReportDto['target_type'], string> = {
  persona: 'persona',
  knowledge_library: 'knowledge library',
}

/**
 * Render a cascade-delete report as a scrollable Markdown summary.
 *
 * Keep the body minimal — the report is purely informational and is meant
 * to give the user confidence about what was actually purged. The Sheet
 * already provides the dismiss-on-Esc / dismiss-on-backdrop behaviour and
 * the dark theme.
 */
export function DeletionReportSheet({
  report,
  onClose,
}: DeletionReportSheetProps) {
  if (!report) return null

  const markdown = buildMarkdown(report)
  const totalWarnings = report.steps.reduce(
    (sum, step) => sum + step.warnings.length,
    0,
  )
  const targetLabel = TARGET_LABEL[report.target_type]

  return (
    <Sheet
      isOpen
      onClose={onClose}
      size="xl"
      ariaLabel={`Deletion report for ${report.target_name}`}
      className="bg-[#0f0d16] text-white/85 border border-white/10"
    >
      <header
        className="px-6 py-4 border-b border-white/10 flex items-center justify-between"
      >
        <div>
          <h2 className="text-[15px] font-semibold text-white/90">
            Deletion report
          </h2>
          <p className="text-[11px] text-white/45 mt-0.5 font-mono">
            {targetLabel} · {report.success ? 'success' : 'partial'}
            {totalWarnings > 0 && (
              <>
                {' · '}
                <span className="text-amber-300/80">
                  {totalWarnings} warning{totalWarnings === 1 ? '' : 's'}
                </span>
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-3 py-1.5 text-[12px] font-medium text-white/70 hover:text-white/90 hover:bg-white/5 transition-colors"
        >
          Close
        </button>
      </header>
      <div
        className="overflow-y-auto px-6 py-5 text-[13px] leading-relaxed deletion-report-body"
        style={{ maxHeight: '70vh' }}
      >
        <ReactMarkdown
          components={{
            h1: ({ children }) => (
              <h1 className="text-[16px] font-semibold text-white/90 mt-0 mb-3">
                {children}
              </h1>
            ),
            h2: ({ children }) => (
              <h2 className="text-[14px] font-semibold text-white/85 mt-5 mb-2">
                {children}
              </h2>
            ),
            ul: ({ children }) => (
              <ul className="list-disc list-inside space-y-1 text-white/80 my-2">
                {children}
              </ul>
            ),
            p: ({ children }) => (
              <p className="text-white/75 my-2">{children}</p>
            ),
            strong: ({ children }) => (
              <strong className="text-white/95 font-semibold">
                {children}
              </strong>
            ),
            code: ({ children }) => (
              <code className="font-mono text-[12px] text-amber-200/85 bg-white/5 px-1 py-0.5 rounded">
                {children}
              </code>
            ),
          }}
        >
          {markdown}
        </ReactMarkdown>
      </div>
    </Sheet>
  )
}

/**
 * Render the structured report as a human-friendly markdown text dump.
 *
 * Keep it short and scannable — each report row becomes one bullet line
 * with the count, label, and any warnings indented underneath.
 */
function buildMarkdown(report: DeletionReportDto): string {
  const targetLabel = TARGET_LABEL[report.target_type]
  const warningTotal = report.steps.reduce(
    (sum, step) => sum + step.warnings.length,
    0,
  )

  const lines: string[] = []
  lines.push(`# ${capitalise(targetLabel)} '${report.target_name}'`)

  if (report.success) {
    lines.push('')
    lines.push(
      `${capitalise(targetLabel)} **'${report.target_name}'** successfully ` +
        `deleted with ${warningTotal} warning${warningTotal === 1 ? '' : 's'}.`,
    )
  } else {
    lines.push('')
    lines.push(
      `**Partial deletion.** The ${targetLabel} document itself could not be ` +
        `removed — see warnings below. Connected data may have been ` +
        `cleaned up regardless.`,
    )
  }

  lines.push('')
  lines.push('## What was removed')
  lines.push('')
  for (const step of report.steps) {
    const icon = step.warnings.length > 0 ? '⚠' : '✓'
    lines.push(
      `- ${icon} **${step.deleted_count}** ${step.label}`,
    )
    for (const warning of step.warnings) {
      lines.push(`  - \`${warning}\``)
    }
  }

  if (warningTotal === 0) {
    lines.push('')
    lines.push('_No warnings — every cleanup step completed cleanly._')
  } else {
    lines.push('')
    lines.push(
      '_Warnings are non-fatal — the cascade continued despite each one. ' +
        'Missing files (already deleted from disk) are NOT counted as warnings._',
    )
  }

  return lines.join('\n')
}

function capitalise(value: string): string {
  if (!value) return value
  return value.charAt(0).toUpperCase() + value.slice(1)
}
