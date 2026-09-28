import React, { useEffect, useRef, useState } from 'react';
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { QRCodeSVG } from 'qrcode.react';
import { API, apiBase, request, sessionJoinUrl, setApiBaseUrl } from './api';

function Shell({ children }) {
  return <main className="shell"><header><Link to="/" className="brand">AI <span>AVLOKAN</span></Link><span className="eyebrow">LIVE KNOWLEDGE ARENA</span></header>{children}</main>;
}

function Home() {
  return <Shell><section className="hero"><p className="kicker">Team-based AI challenge</p><h1>Think clearly.<br /><em>Answer quickly.</em></h1><p className="lede">A focused live quiz room for curious teams, hosted by your AI Avlokan crew.</p><div className="actions"><Link className="button primary" to="/join">Join a quiz</Link><Link className="button ghost" to="/admin/login">Host console</Link></div></section></Shell>;
}

function Join() {
  const { sessionCode = '' } = useParams();
  const [code, setCode] = useState(sessionCode);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();
  async function submit(event) {
    event.preventDefault();
    setError('');
    try {
      const data = await request('/api/join', { method: 'POST', body: JSON.stringify({ session_code: code, team_name: name }) });
      localStorage.setItem('teamId', data.team_id);
      navigate(`/waiting/${data.team_id}`);
    } catch (requestError) { setError(requestError.message); }
  }
  return <Shell><section className="panel narrow"><p className="kicker">Participant entrance</p><h2>Join your quiz</h2><p className="muted">Enter the code shared by your host and your team name.</p><form onSubmit={submit}><label>Quiz code<input value={code} onChange={event => setCode(event.target.value.toUpperCase())} required maxLength="8" placeholder="AVLOKAN7" /></label><label>Team name<input value={name} onChange={event => setName(event.target.value)} required placeholder="Team Aurora" /></label>{error && <p className="error">{error}</p>}<button className="button primary wide">Enter waiting room</button></form></section></Shell>;
}

function useQuiz(teamId) {
  const [state, setState] = useState(null);
  const refresh = () => request(`/api/quiz/${teamId}/status`).then(setState).catch(() => {});
  useEffect(() => {
    const refreshAfterHistory = () => refresh();
    refresh();
    const timer = setInterval(refresh, 1000);
    window.addEventListener('pageshow', refreshAfterHistory);
    window.addEventListener('popstate', refreshAfterHistory);
    return () => {
      clearInterval(timer);
      window.removeEventListener('pageshow', refreshAfterHistory);
      window.removeEventListener('popstate', refreshAfterHistory);
    };
  }, [teamId]);
  return [state, refresh];
}

function Waiting() {
  const { teamId } = useParams();
  const [state] = useQuiz(teamId);
  const navigate = useNavigate();
  useEffect(() => {
    if (state?.status === 'active' || state?.status === 'paused') navigate(`/quiz/${teamId}`);
    if (state?.status === 'completed') navigate(`/completed/${teamId}`, { replace: true });
  }, [state, teamId, navigate]);
  async function enterFullscreen() {
    try { await document.documentElement.requestFullscreen(); } catch { }
  }
  return <Shell><section className="panel waiting"><div className="pulse" /><p className="kicker">You are checked in</p><h2>{state?.team_name || 'Your team'} is ready.</h2><p className="muted">Keep this window open. The host will start the room shortly.</p><button className="button ghost" onClick={enterFullscreen}>Enter fullscreen</button><div className="waiting-code">WAITING FOR HOST</div></section></Shell>;
}

function Quiz() {
  const { teamId } = useParams();
  const [state, refresh] = useQuiz(teamId);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState('');
  const [awayWarning, setAwayWarning] = useState(false);
  const activeAway = useRef(false);
  const blurTimer = useRef(null);
  const eventQueue = useRef(Promise.resolve());
  const lastPointEvent = useRef({});
  const hadFullscreen = useRef(Boolean(document.fullscreenElement));
  useEffect(() => {
    let mounted = true;
    const sendActivity = activityType => {
      eventQueue.current = eventQueue.current
        .then(() => request(`/api/quiz/${teamId}/activity`, { method: 'POST', body: JSON.stringify({ activity_type: activityType }) }))
        .catch(() => {});
      return eventQueue.current;
    };
    const beginAway = activityType => {
      if (activeAway.current) return;
      activeAway.current = true;
      sendActivity(activityType);
    };
    const returnToQuiz = activityType => {
      if (!activeAway.current) return;
      activeAway.current = false;
      setAwayWarning(true);
      sendActivity(activityType);
      window.setTimeout(() => { if (mounted) setAwayWarning(false); }, 7000);
    };
    eventQueue.current = eventQueue.current
      .then(() => request(`/api/quiz/${teamId}/activity`, { method: 'POST', body: JSON.stringify({ activity_type: 'TAB_VISIBLE' }) }))
      .then(result => { if (mounted && result.returned) setAwayWarning(true); })
      .catch(() => {});
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        window.clearTimeout(blurTimer.current);
        beginAway('TAB_HIDDEN');
      } else {
        returnToQuiz('TAB_VISIBLE');
      }
    };
    const onBlur = () => {
      window.clearTimeout(blurTimer.current);
      blurTimer.current = window.setTimeout(() => {
        if (document.visibilityState === 'visible') beginAway('WINDOW_BLUR');
      }, 250);
    };
    const onFocus = () => {
      window.clearTimeout(blurTimer.current);
      if (document.visibilityState === 'visible') returnToQuiz('WINDOW_FOCUS');
    };
    const onFullscreenChange = () => {
      if (hadFullscreen.current && !document.fullscreenElement) sendActivity('FULLSCREEN_EXIT');
      hadFullscreen.current = Boolean(document.fullscreenElement);
    };
    const onClipboard = (event, activityType) => {
      event.preventDefault();
      const nowMs = Date.now();
      if (nowMs - (lastPointEvent.current[activityType] || 0) < 1000) return;
      lastPointEvent.current[activityType] = nowMs;
      sendActivity(activityType);
    };
    const onCopy = event => onClipboard(event, 'COPY_ATTEMPT');
    const onPaste = event => onClipboard(event, 'PASTE_ATTEMPT');
    const onCut = event => onClipboard(event, 'CUT_ATTEMPT');
    const stopContextMenu = event => event.preventDefault();
    const onKeyDown = event => {
      if (!(event.ctrlKey || event.metaKey) || !['c', 'v', 'x'].includes(event.key.toLowerCase())) return;
      event.preventDefault();
      const activityType = { c: 'COPY_ATTEMPT', v: 'PASTE_ATTEMPT', x: 'CUT_ATTEMPT' }[event.key.toLowerCase()];
      const nowMs = Date.now();
      if (nowMs - (lastPointEvent.current[activityType] || 0) >= 1000) {
        lastPointEvent.current[activityType] = nowMs;
        sendActivity(activityType);
      }
    };
    const onPageHide = () => {
      if (activeAway.current) return;
      activeAway.current = true;
      fetch(`${apiBase}/api/quiz/${teamId}/activity`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ activity_type: 'WINDOW_BLUR' }), keepalive: true }).catch(() => {});
    };
    document.addEventListener('visibilitychange', onVisibility);
    document.addEventListener('copy', onCopy);
    document.addEventListener('paste', onPaste);
    document.addEventListener('cut', onCut);
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('contextmenu', stopContextMenu);
    document.addEventListener('fullscreenchange', onFullscreenChange);
    window.addEventListener('blur', onBlur);
    window.addEventListener('focus', onFocus);
    window.addEventListener('pagehide', onPageHide);
    return () => {
      mounted = false;
      window.clearTimeout(blurTimer.current);
      document.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('copy', onCopy);
      document.removeEventListener('paste', onPaste);
      document.removeEventListener('cut', onCut);
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('contextmenu', stopContextMenu);
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('pagehide', onPageHide);
    };
  }, [teamId]);
  async function answer(option) {
    if (locked) return;
    setLocked(true); setError('');
    try { await request(`/api/quiz/${teamId}/answer`, { method: 'POST', body: JSON.stringify({ selected_option: option, question_number: state.current_question }) }); await refresh(); }
    catch (requestError) { setError(requestError.message); await refresh(); }
    finally { setLocked(false); }
  }
  if (!state) return <Shell><section className="panel"><p>Connecting to the quiz...</p></section></Shell>;
  if (state.status === 'completed') return <Navigate to={`/completed/${teamId}`} replace />;
  if (state.status !== 'active' && state.status !== 'paused') return <Waiting />;
  const isPaused = state.status === 'paused' || state.is_paused;
  const seconds = Math.ceil(state.remaining_seconds);
  return <Shell><section className="quiz"><div className="quiz-top"><span className="brand">AI <span>AVLOKAN</span></span><span className="team-chip">TEAM / {state.team_name}</span></div><div className="quiz-meta"><span>QUESTION {state.current_question} / {state.total_questions}</span><strong className={isPaused ? 'paused-timer' : (seconds <= 10 ? 'urgent' : '')}>{seconds}<small>{isPaused ? ' SEC (PAUSED)' : ' SEC'}</small></strong></div>{isPaused && <div className="quiz-paused-card" role="alert"><div className="paused-pill">⏸ QUIZ PAUSED BY HOST</div><p>The host has temporarily paused the quiz. The timer is frozen at <strong>{seconds}s</strong>. Options are disabled until the quiz resumes.</p></div>}{state.question?.challenge && <div className="challenge-tag">CHALLENGE</div>}<h2>{state.question?.text}</h2><div className={`options ${isPaused ? 'is-paused' : ''}`}>{state.question?.options && Object.entries(state.question.options).map(([letter, text]) => <button disabled={locked || isPaused} onClick={() => answer(letter)} key={letter}><b>{letter}</b>{text}</button>)}</div>{awayWarning && <p className="activity-warning" role="status">Quiz screen was inactive. Your timer continued while you were away.</p>}{error && <p className="error">{error}</p>}<p className="muted footer-note">{isPaused ? 'Quiz is paused. Please wait for the host to resume.' : 'Your answer submits instantly. Stay focused on this window.'}</p></section></Shell>;
}

function Completed() {
  const { teamId } = useParams();
  const [state] = useQuiz(teamId);
  if (!state) return <Shell><section className="panel"><p>Checking quiz status...</p></section></Shell>;
  if (state.status === 'active') return <Navigate to={`/quiz/${teamId}`} replace />;
  if (state.status === 'waiting') return <Navigate to={`/waiting/${teamId}`} replace />;
  return (
    <Shell>
      <section className="panel completed">
        <div className="check">✓</div>
        <p className="kicker">Submission received</p>
        <h2>Quiz Completed</h2>
        <p className="muted">{state.team_name} has finished this quiz session.</p>
        <div className="completion-notice">
          <p className="completion-main-text">Thank you for participating! Your answers have been recorded.</p>
          <p className="completion-subtext">The final results and leaderboard will be announced by the host.</p>
        </div>
        <Link className="button ghost" to="/">Return home</Link>
      </section>
    </Shell>
  );
}

function AdminLogin() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [customApi, setCustomApi] = useState(API);
  const [showApiInput, setShowApiInput] = useState(API.includes('vercel.app'));
  const navigate = useNavigate();

  async function submit(event) {
    event.preventDefault();
    setError('');
    try {
      const data = await request('/api/admin/login', { method: 'POST', body: JSON.stringify({ password }) });
      localStorage.setItem('adminToken', data.token);
      navigate('/admin');
    } catch (requestError) {
      if (API.includes('vercel.app')) {
        setError('The frontend is currently calling Vercel instead of your Render backend. Please set your Render Backend URL below.');
        setShowApiInput(true);
      } else {
        setError(requestError.message || 'Login failed. Please check your password or backend connection.');
      }
    }
  }

  function handleSaveApi(event) {
    event.preventDefault();
    if (customApi) {
      setApiBaseUrl(customApi);
    }
  }

  return (
    <Shell>
      <section className="panel narrow">
        <p className="kicker">Organizer access</p>
        <h2>Host console</h2>
        <form onSubmit={submit}>
          <label>
            Admin password
            <input type="password" value={password} onChange={event => setPassword(event.target.value)} required />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="button primary wide">Sign in</button>
        </form>

        <div className="api-config-box" style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid var(--panel-border)' }}>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '0 0 8px' }}>
            Connected Backend: <code style={{ color: 'var(--accent)', background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: '4px' }}>{API}</code>
            {' · '}
            <button type="button" onClick={() => setShowApiInput(!showApiInput)} style={{ background: 'none', border: 'none', color: 'var(--accent)', padding: 0, textDecoration: 'underline', cursor: 'pointer', fontSize: '12px' }}>
              {showApiInput ? 'Hide' : 'Change Backend URL'}
            </button>
          </p>
          {showApiInput && (
            <form onSubmit={handleSaveApi} style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
              <input
                type="url"
                value={customApi}
                onChange={event => setCustomApi(event.target.value)}
                placeholder="https://your-backend.onrender.com"
                style={{ flex: 1, padding: '8px 12px', fontSize: '13px' }}
                required
              />
              <button type="submit" className="button ghost" style={{ padding: '8px 14px', fontSize: '13px', whiteSpace: 'nowrap' }}>
                Save & Connect
              </button>
            </form>
          )}
        </div>
      </section>
    </Shell>
  );
}

function AdminHistory() {
  const { sessionId } = useParams();
  const [sessions, setSessions] = useState([]);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');
  const token = localStorage.getItem('adminToken');
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    if (!token) return;
    setError('');
    if (sessionId) {
      setResults(null);
      request(`/api/admin/results/${sessionId}`, { headers }).then(setResults).catch(requestError => setError(requestError.message));
      return;
    }
    setResults(null);
    request('/api/admin/sessions/history', { headers }).then(setSessions).catch(requestError => setError(requestError.message));
  }, [sessionId, token]);

  if (!token) return <AdminLogin />;
  return <Shell><section className="dashboard"><div className="dash-head"><div><p className="kicker">AI AVLOKAN</p><h2>{results ? `Quiz Session ${results.session.code}` : 'Quiz History'}</h2></div><Link className="button ghost" to="/admin">Current Quiz</Link></div>{error && <p className="error">{error}</p>}
    {sessionId && results && <><p className="muted">Date: {new Date(results.session.created_at).toLocaleString()} · Teams: {results.session.team_count} · Status: {results.session.status}</p><h3>Final Leaderboard</h3><div className="table-wrap"><table><thead><tr><th>Rank</th><th>Team Name</th><th>Score</th><th>Tab Switches</th><th>Total Time Away</th><th>Correct</th><th>Wrong</th><th>Unanswered</th></tr></thead><tbody>{results.leaderboard.length ? results.leaderboard.map(team => <tr key={team.rank}><td>{team.rank}</td><td>{team.team_name}</td><td>{team.score}</td><td>{team.tab_switches}</td><td>{team.total_away_seconds.toFixed(1)} sec</td><td>{team.correct}</td><td>{team.wrong}</td><td>{team.unanswered}</td></tr>) : <tr><td colSpan="8">No teams participated in this session.</td></tr>}</tbody></table></div></>}
    {!sessionId && <><h3>Previously conducted quizzes</h3><div className="history-list">{sessions.length ? sessions.map((session, index) => <article className="history-row" key={session.id}><div><h3>Quiz Session {sessions.length - index}</h3><p>Date: {new Date(session.completed_at || session.created_at).toLocaleString()}</p><p>Teams: {session.team_count} · Status: {session.status}</p></div><Link className="button primary" to={`/admin/history/${session.id}`}>View Leaderboard</Link></article>) : <p className="muted">No completed quiz sessions yet.</p>}</div></>}
  </section></Shell>;
}

function Admin() {
  const [created, setCreated] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [copied, setCopied] = useState(false);
  const [teamDetail, setTeamDetail] = useState(null);
  const token = localStorage.getItem('adminToken');
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    if (!token) return;
    request('/api/admin/session/current', { headers }).then(current => {
      if (!current) return;
      setCreated({ ...current.session, join_url: sessionJoinUrl(current.session) });
      setData(current.dashboard);
    }).catch(requestError => setError(requestError.message));
  }, [token]);

  async function create() {
    try {
      const value = await request('/api/admin/session/create', { method: 'POST', headers });
      setCreated({ ...value, join_url: sessionJoinUrl(value) });
      await load(value.id);
    } catch (requestError) { setError(requestError.message); }
  }

  async function load(id) {
    try { setData(await request(`/api/admin/session/${id}`, { headers })); }
    catch (requestError) { setError(requestError.message); }
  }

  async function start() {
    setError('');
    try {
      const updated = await request(`/api/admin/session/${created.id}/start`, { method: 'POST', headers });
      setData(updated);
      setNotice('Quiz started successfully!');
      setTimeout(() => setNotice(''), 3000);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function pause() {
    setError('');
    try {
      const updated = await request(`/api/admin/session/${created.id}/pause`, { method: 'POST', headers });
      setData(updated);
      setNotice('Quiz paused. Participant timers are frozen.');
      setTimeout(() => setNotice(''), 3000);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function resume() {
    setError('');
    try {
      const updated = await request(`/api/admin/session/${created.id}/resume`, { method: 'POST', headers });
      setData(updated);
      setNotice('Quiz resumed! Countdown continued.');
      setTimeout(() => setNotice(''), 3000);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function stop() {
    const confirmed = window.confirm(
      'Are you sure you want to stop the quiz?\n\nThis will freeze all questions and conclude the quiz session.'
    );
    if (!confirmed) return;
    setError('');
    try {
      const updated = await request(`/api/admin/session/${created.id}/stop`, { method: 'POST', headers });
      setData(updated);
      setNotice('Quiz stopped and marked as completed.');
      setTimeout(() => setNotice(''), 3000);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function reset() {
    const confirmed = window.confirm('Start a new quiz session for the next group?\n\nPrevious quiz results will be preserved in Quiz History.');
    if (!confirmed) return;
    try {
      const result = await request('/api/admin/session/reset', { method: 'POST', headers });
      setCreated({ ...result.session, join_url: sessionJoinUrl(result.session) });
      setData(result.dashboard);
      setTeamDetail(null);
      setNotice(result.message);
      setError('');
    } catch (requestError) { setError(requestError.message); }
  }

  async function inspectTeam(teamId) {
    try { setTeamDetail(await request(`/api/admin/team/${teamId}`, { headers })); }
    catch (requestError) { setError(requestError.message); }
  }

  useEffect(() => {
    if (!created) return undefined;
    const timer = setInterval(() => load(created.id), 1500);
    return () => clearInterval(timer);
  }, [created]);

  useEffect(() => {
    if (!teamDetail) return undefined;
    const timer = setInterval(() => {
      request(`/api/admin/team/${teamDetail.team.id}`, { headers }).then(setTeamDetail).catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
  }, [teamDetail?.team?.id, token]);

  if (!token) return <AdminLogin />;
  const distribution = data?.distribution || {};
  const affected = team => team.affected_questions.length ? team.affected_questions.map(question => `Q${question}`).join(', ') : '—';
  const activityLabel = type => ({ TAB_HIDDEN: 'Quiz page inactive', WINDOW_BLUR: 'Window lost focus', TAB_VISIBLE: 'Tab became visible', WINDOW_FOCUS: 'Window regained focus', RETURNED_TO_QUIZ: 'Returned to quiz', FULLSCREEN_EXIT: 'Fullscreen exited', COPY_ATTEMPT: 'Copy attempt', PASTE_ATTEMPT: 'Paste attempt', CUT_ATTEMPT: 'Cut attempt' }[type] || type);

  return <Shell><section className="dashboard">
    <div className="dash-head">
      <div>
        <p className="kicker">AI AVLOKAN HOST DASHBOARD</p>
        <div className="session-title-row">
          <h2>{created ? `Session ${created.code}` : 'Create a live room'}</h2>
          {data?.session?.status && (
            <span className={`status-badge status-${data.session.status}`}>
              <span className="status-dot" />
              {data.session.status.toUpperCase()}
            </span>
          )}
        </div>
      </div>
      <div className="actions">
        {!created && <button className="button primary" onClick={create}>Create session</button>}
        <Link className="button ghost" to="/admin/history">Quiz History</Link>
      </div>
    </div>
    {notice && <p className="success">{notice}</p>}{error && <p className="error">{error}</p>}{created && !data && <p className="muted">Loading room...</p>}
    {created && data && <>
      <div className="room-tools">
        <div className="room-info">
          <span className="label">Participant Join URL</span>
          <div className="url-copy-row">
            <a href={created.join_url} target="_blank" rel="noreferrer" className="join-link">{created.join_url}</a>
            <button type="button" className="copy-btn" onClick={() => { if (navigator.clipboard) { navigator.clipboard.writeText(created.join_url); } setCopied(true); setTimeout(() => setCopied(false), 2000); }}>
              {copied ? '✓ Copied' : 'Copy Link'}
            </button>
          </div>
          <p className="qr-hint">Scan with any phone camera on the same Wi-Fi network to join.</p>
          <div className="room-actions control-bar">
            {data.session.status === 'waiting' && (
              <button
                className="button primary btn-start"
                onClick={start}
                disabled={!data.teams.length}
                title={!data.teams.length ? 'Wait for teams to join before starting' : 'Start the quiz'}
              >
                <span className="btn-icon">▶</span> Start quiz
              </button>
            )}
            {data.session.status === 'active' && (
              <>
                <button className="button pause btn-pause" onClick={pause} title="Pause quiz and freeze participant timers">
                  <span className="btn-icon">⏸</span> Pause quiz
                </button>
                <button className="button danger btn-stop" onClick={stop} title="Stop and finalize the quiz session">
                  <span className="btn-icon">⏹</span> Stop quiz
                </button>
              </>
            )}
            {data.session.status === 'paused' && (
              <>
                <button className="button resume btn-resume" onClick={resume} title="Resume quiz countdown">
                  <span className="btn-icon">▶</span> Resume quiz
                </button>
                <button className="button danger btn-stop" onClick={stop} title="Stop and finalize the quiz session">
                  <span className="btn-icon">⏹</span> Stop quiz
                </button>
              </>
            )}
            {(data.session.status === 'completed' || data.session.status === 'archived') && (
              <>
                <button className="button danger" onClick={reset} title="Archive session and create a new room">
                  Start New Quiz
                </button>
                <Link className="button ghost" to={`/admin/history/${created.id}`}>
                  View Final Results
                </Link>
              </>
            )}
          </div>
        </div>
        <div className="qr-card">
          <QRCodeSVG value={created.join_url} size={150} bgColor="#ffffff" fgColor="#14232d" level="M" />
          <span className="qr-scan-label">Scan to Join</span>
        </div>
      </div>
      <div className="stat-grid"><div><span>Teams connected</span><strong>{data.teams.length} / 100</strong></div><div><span>Current question</span><strong>{data.session.current_question} / 30</strong></div><div><span>Answer distribution</span><strong>A {distribution.A || 0}  B {distribution.B || 0}  C {distribution.C || 0}  D {distribution.D || 0}  Unanswered {distribution.unanswered || 0}</strong></div></div>
      <div className="fastest"><span className="label">Fastest correct answers</span>{data.fastest.length ? data.fastest.map((item, index) => <span key={`${item.team_name}-${item.seconds}`}>{index + 1}. {item.team_name} - {item.seconds}s</span>) : <span className="muted">No correct answers for the current question yet.</span>}</div>
      <section className="integrity-section"><h3>Activity / Integrity</h3><p className="muted integrity-note">These indicators show that the quiz page became inactive or lost focus. They do not prove which external application or website was used.</p><div className="table-wrap"><table><thead><tr><th>Team Name</th><th>Score</th><th>Tab Switches</th><th>Total Time Away</th><th>Questions Affected</th><th>Current Status</th></tr></thead><tbody>{data.teams.length ? data.teams.map(team => <tr key={`integrity-${team.id}`} onClick={() => inspectTeam(team.id)} className="clickable-row"><td>{team.team_name}</td><td>{team.score}</td><td>{team.tab_switches}</td><td>{team.away_seconds.toFixed(1)} sec{team.current_activity ? ' (away)' : ''}</td><td>{affected(team)}</td><td>{team.current_activity ? 'Quiz page inactive' : team.status}</td></tr>) : <tr><td colSpan="6">No teams yet.</td></tr>}</tbody></table></div></section>
      {teamDetail && <section className="activity-timeline"><div className="timeline-heading"><h3>{teamDetail.team.team_name} Activity Timeline</h3><button className="button ghost" onClick={() => setTeamDetail(null)}>Close</button></div>{teamDetail.activities.length ? <ol>{teamDetail.activities.map((activity, index) => <li key={`${activity.started_at}-${index}`}><strong>Q{activity.question_number}</strong> — {activityLabel(activity.activity_type)}{activity.duration_seconds !== null && ` — ${activity.duration_seconds.toFixed(1)} sec`}{activity.returned_at === null && activity.activity_type !== 'RETURNED_TO_QUIZ' && ' — ongoing'}</li>)}</ol> : <p className="muted">No recorded browser activity.</p>}<p>Total switches: {teamDetail.team.tab_switches} · Total time away: {teamDetail.team.away_seconds.toFixed(1)} sec · Questions affected: {affected(teamDetail.team)}</p></section>}
      <h3>FINAL TOP 10</h3><div className="table-wrap"><table><thead><tr><th>Rank</th><th>Team Name</th><th>Score</th><th>Tab Switches</th><th>Total Time Away</th><th>Questions Affected</th></tr></thead><tbody>{data.leaderboard.length ? data.leaderboard.map(team => <tr key={`top-${team.id}`}><td>{team.rank}</td><td>{team.team_name}</td><td>{team.score}</td><td>{team.tab_switches}</td><td>{team.away_seconds.toFixed(1)} sec</td><td>{affected(team)}</td></tr>) : <tr><td colSpan="6">No teams yet.</td></tr>}</tbody></table></div>
      <h3>ALL TEAMS</h3><div className="table-wrap"><table><thead><tr><th>Rank</th><th>Team</th><th>Question</th><th>Score</th><th>Switches</th><th>Away</th><th>Affected Questions</th><th>Correct</th><th>Wrong</th><th>Unanswered</th><th>Status</th></tr></thead><tbody>{data.teams.length ? data.teams.map(team => <tr key={team.id} onClick={() => inspectTeam(team.id)} className="clickable-row"><td>{team.rank}</td><td>{team.team_name}</td><td>{team.current_question}</td><td>{team.score}</td><td>{team.tab_switches}</td><td>{team.away_seconds.toFixed(1)}s</td><td>{affected(team)}</td><td>{team.correct}</td><td>{team.wrong}</td><td>{team.unanswered}</td><td><span className={`status ${team.status}`}>{team.status}</span></td></tr>) : <tr><td colSpan="11">No teams yet.</td></tr>}</tbody></table></div>
    </>}
  </section></Shell>;
}

export default function App() {
  return <Routes><Route path="/" element={<Home />} /><Route path="/join" element={<Join />} /><Route path="/join/:sessionCode" element={<Join />} /><Route path="/waiting/:teamId" element={<Waiting />} /><Route path="/quiz/:teamId" element={<Quiz />} /><Route path="/completed/:teamId" element={<Completed />} /><Route path="/admin/login" element={<AdminLogin />} /><Route path="/admin/history/:sessionId" element={<AdminHistory />} /><Route path="/admin/history" element={<AdminHistory />} /><Route path="/admin" element={<Admin />} /><Route path="*" element={<Home />} /></Routes>;
}
