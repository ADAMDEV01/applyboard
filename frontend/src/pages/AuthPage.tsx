import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'

interface Props {
  mode: 'login' | 'register'
}

export function AuthPage({ mode }: Props) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [demoSubmitting, setDemoSubmitting] = useState(false)

  if (mode === 'login' && api.hasToken()) return <Navigate to="/" replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      if (mode === 'register') {
        await api.register(email, password)
        navigate('/login?registered=1', { replace: true })
      } else {
        await api.login(email, password)
        navigate('/', { replace: true })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed.')
    } finally {
      setSubmitting(false)
    }
  }

  async function tryDemo() {
    setError('')
    setDemoSubmitting(true)
    try {
      await api.demoLogin()
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Demo sign-in failed.')
    } finally {
      setDemoSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <Link className="brand auth-brand" to="/">
          <span className="brand-mark">A</span><span>Applyboard</span>
        </Link>
        <p className="eyebrow">{mode === 'login' ? 'WELCOME BACK' : 'START ORGANIZING'}</p>
        <h1>{mode === 'login' ? 'Sign in to your tracker' : 'Create your account'}</h1>
        <p className="muted">
          {mode === 'login'
            ? 'Keep every opportunity moving forward.'
            : 'A clear view of every application and next step.'}
        </p>
        {searchParams.has('registered') && <p className="success-message">Account created. Sign in to continue.</p>}
        {searchParams.has('expired') && <p className="form-error">Your session expired. Please sign in again.</p>}
        <form className="auth-form" onSubmit={submit}>
          <label>Email address
            <input autoComplete="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>Password
            <input autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="button button-primary button-wide" disabled={submitting} type="submit">
            {submitting ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        {mode === 'login' && (
          <button className="button button-quiet button-wide demo-button" disabled={demoSubmitting || submitting} onClick={tryDemo} type="button">
            {demoSubmitting ? 'Opening demo…' : 'Try the demo workspace'}
          </button>
        )}
        <p className="auth-switch">
          {mode === 'login' ? 'New to Applyboard?' : 'Already have an account?'}{' '}
          <Link to={mode === 'login' ? '/register' : '/login'}>
            {mode === 'login' ? 'Create an account' : 'Sign in'}
          </Link>
        </p>
      </section>
      <aside className="auth-aside">
        <p className="eyebrow">YOUR SEARCH, IN FOCUS</p>
        <h2>Make the next move with confidence.</h2>
        <p>One thoughtful workspace for applications, follow-ups, and the signals that matter.</p>
      </aside>
    </main>
  )
}
