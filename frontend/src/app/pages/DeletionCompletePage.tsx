import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { authApi } from '../../core/api/auth'
import { ApiError } from '../../core/api/client'
import { DeletionReportBody } from '../../core/components/DeletionReportSheet'
import type { DeletionReportDto } from '../../core/types/deletion'

type State =
  | { kind: 'loading' }
  | { kind: 'success'; report: DeletionReportDto }
  | { kind: 'expired' }
  | { kind: 'error'; message: string }

/**
 * Public landing page shown to a user immediately after they self-delete.
 *
 * The slug is a short-lived (15-minute Redis TTL) opaque token issued by
 * `DELETE /api/users/me` — it lets the logged-out client fetch their own
 * deletion report without authentication. After the TTL expires the slug
 * returns 410 Gone and we show a friendly "report expired" message.
 */
export default function DeletionCompletePage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    if (!slug) {
      setState({ kind: 'expired' })
      return
    }
    let cancelled = false
    authApi
      .getDeletionReport(slug)
      .then((report) => {
        if (cancelled) return
        setState({ kind: 'success', report })
      })
      .catch((err) => {
        if (cancelled) return
        if (
          err instanceof ApiError &&
          (err.status === 410 || err.status === 404)
        ) {
          setState({ kind: 'expired' })
          return
        }
        setState({
          kind: 'error',
          message:
            err instanceof Error
              ? err.message
              : 'Could not load your deletion report.',
        })
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  function goToLogin() {
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-dvh bg-base text-white/85 px-4 py-10 pb-[max(2.5rem,env(safe-area-inset-bottom))]">
      <div className="mx-auto w-full max-w-2xl">
        {state.kind === 'loading' && (
          <p className="text-center text-[13px] text-white/45 font-mono mt-20">
            Loading your deletion report…
          </p>
        )}

        {state.kind === 'expired' && (
          <div className="mt-16 rounded-xl border border-white/8 bg-surface p-8 text-center">
            <h1 className="text-[18px] font-semibold text-white/90 mb-3">
              This deletion report has expired.
            </h1>
            <p className="text-[13px] text-white/55 leading-relaxed mb-6">
              Reports are kept for 15 minutes — if you closed the tab, that's
              fine: all your data has still been permanently deleted.
            </p>
            <button
              type="button"
              onClick={goToLogin}
              className="rounded-lg bg-white/10 hover:bg-white/15 px-5 py-2 text-[13px] font-medium text-white/80 transition-colors"
            >
              Go to login
            </button>
          </div>
        )}

        {state.kind === 'error' && (
          <div className="mt-16 rounded-xl border border-red-400/20 bg-red-500/5 p-8 text-center">
            <h1 className="text-[18px] font-semibold text-white/90 mb-3">
              Could not load your deletion report.
            </h1>
            <p className="text-[13px] text-red-300/80 font-mono leading-relaxed mb-6">
              {state.message}
            </p>
            <p className="text-[12px] text-white/45 leading-relaxed mb-6">
              Your account has still been permanently deleted — this page is
              only the receipt.
            </p>
            <button
              type="button"
              onClick={goToLogin}
              className="rounded-lg bg-white/10 hover:bg-white/15 px-5 py-2 text-[13px] font-medium text-white/80 transition-colors"
            >
              Go to login
            </button>
          </div>
        )}

        {state.kind === 'success' && (
          <div>
            <div className="text-center mb-8 mt-6">
              <h1 className="text-[22px] font-semibold text-white/90 mb-3">
                Your data has been deleted.
              </h1>
              <p className="text-[13px] text-white/55 leading-relaxed max-w-xl mx-auto">
                Everything we stored about you has been purged from the
                database and filesystem. Below is a line-by-line receipt. It is
                kept for 15 minutes — feel free to copy or screenshot it.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-[#0f0d16] overflow-hidden">
              <div className="px-6 py-5 text-[13px] leading-relaxed deletion-report-body">
                <DeletionReportBody report={state.report} />
              </div>
            </div>
            <div className="flex justify-center mt-8">
              <button
                type="button"
                onClick={goToLogin}
                className="rounded-lg bg-white/10 hover:bg-white/15 px-6 py-2.5 text-[13px] font-medium text-white/80 transition-colors"
              >
                Go to login
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
