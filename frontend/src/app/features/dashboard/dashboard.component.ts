import { Component, OnInit, AfterViewInit, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { AuthService } from '../../core/services/auth.service';
import { environment } from '../../../environments/environment';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

interface ChatMessage {
  text: string;
  isUser: boolean;
  html?: SafeHtml;
}

interface SessionData {
  title: string;
  messages: { text: string; isUser: boolean }[];
  updatedAt: number;
}

const sessionsKey = (username: string) => `vdt_chat_sessions_${username}`;
const legacyKey  = (username: string) => `vdt_chat_session_${username}`;

const WELCOME_TEXT =
  'Hello! I am your AI Data Agent. I can query market data while respecting your access level.\n\n' +
  'Try asking:\n' +
  '- **Show my total trading volume**\n' +
  '- **Create a bar chart of orders by sector**\n' +
  '- **What tickers did I trade this month?**';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.css']
})
export class DashboardComponent implements OnInit, AfterViewInit {
  @ViewChild('chatScroll') private chatScrollRef!: ElementRef<HTMLElement>;

  username = '';
  sessionId: string = crypto.randomUUID();
  chatQuery = '';
  messages: ChatMessage[] = [];
  isChatLoading = false;
  isChatOpen = false;
  showHistory = false;
  supersetIframeUrl: any = null;

  private allSessions: Record<string, SessionData> = {};

  get sessionList(): { id: string; title: string; updatedAt: number }[] {
    return Object.entries(this.allSessions)
      .map(([id, s]) => ({ id, title: s.title, updatedAt: s.updatedAt }))
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }

  constructor(
    private authService: AuthService,
    private router: Router,
    private http: HttpClient,
    private sanitizer: DomSanitizer
  ) {}

  ngOnInit(): void {
    if (!this.authService.isAuthenticated()) {
      this.router.navigate(['/login']);
      return;
    }
    const token = this.authService.getToken();
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        this.username = payload.sub || 'User';
      } catch {
        this.username = 'User';
      }
    }
    this.loadSession();
  }

  ngAfterViewInit(): void {
    this.embedSuperset();
    this.scrollToBottom();
  }

  // ── Session persistence ──────────────────────────────────────────────────

  private loadSession(): void {
    try {
      const newRaw = localStorage.getItem(sessionsKey(this.username));
      if (!newRaw) {
        // Migrate legacy single-session format
        const legacyRaw = localStorage.getItem(legacyKey(this.username));
        if (legacyRaw) {
          const legacy = JSON.parse(legacyRaw);
          const id = legacy.sessionId || crypto.randomUUID();
          const msgs: { text: string; isUser: boolean }[] = legacy.messages || [];
          const firstUser = msgs.find(m => m.isUser);
          this.allSessions[id] = {
            title: firstUser ? firstUser.text.slice(0, 42) : 'Previous chat',
            messages: msgs,
            updatedAt: Date.now()
          };
          this.sessionId = id;
          localStorage.removeItem(legacyKey(this.username));
        }
      } else {
        const data = JSON.parse(newRaw);
        this.allSessions = data.sessions || {};
        const activeId: string = data.activeSessionId;
        if (activeId && this.allSessions[activeId]) {
          this.sessionId = activeId;
        } else {
          const sorted = Object.entries(this.allSessions)
            .sort(([, a], [, b]) => b.updatedAt - a.updatedAt);
          if (sorted.length) this.sessionId = sorted[0][0];
        }
      }
    } catch {
      // corrupt storage — start fresh
    }

    const current = this.allSessions[this.sessionId];
    if (current) {
      this.messages = current.messages.map(m => ({
        text: m.text,
        isUser: m.isUser,
        html: !m.isUser ? this.renderMarkdown(m.text) : undefined
      }));
    } else {
      this.messages = [];
      this.pushAgentMessage(WELCOME_TEXT);
      this.saveSession();
    }
  }

  private saveSession(): void {
    const firstUser = this.messages.find(m => m.isUser);
    this.allSessions[this.sessionId] = {
      title: firstUser ? firstUser.text.slice(0, 42) : 'New conversation',
      messages: this.messages.map(m => ({ text: m.text, isUser: m.isUser })),
      updatedAt: Date.now()
    };
    this.saveAllSessions();
  }

  private saveAllSessions(): void {
    localStorage.setItem(
      sessionsKey(this.username),
      JSON.stringify({ activeSessionId: this.sessionId, sessions: this.allSessions })
    );
  }

  newSession(): void {
    this.saveSession();
    this.sessionId = crypto.randomUUID();
    this.messages = [];
    this.pushAgentMessage(WELCOME_TEXT);
    this.saveSession();
    this.showHistory = false;
    this.scrollToBottom();
  }

  switchSession(id: string): void {
    if (id === this.sessionId) { this.showHistory = false; return; }
    this.saveSession();
    this.sessionId = id;
    const session = this.allSessions[id];
    this.messages = session.messages.map(m => ({
      text: m.text,
      isUser: m.isUser,
      html: !m.isUser ? this.renderMarkdown(m.text) : undefined
    }));
    this.saveAllSessions();
    this.showHistory = false;
    setTimeout(() => this.scrollToBottom(), 60);
  }

  deleteSession(id: string, event: Event): void {
    event.stopPropagation();
    delete this.allSessions[id];
    if (id === this.sessionId) {
      const remaining = Object.keys(this.allSessions);
      if (remaining.length) {
        this.switchSession(remaining[0]);
      } else {
        this.newSession();
      }
      return;
    }
    this.saveAllSessions();
  }

  toggleHistory(): void {
    this.showHistory = !this.showHistory;
  }

  formatSessionDate(ts: number): string {
    const d = new Date(ts);
    const diff = Date.now() - ts;
    if (diff < 86_400_000) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (diff < 604_800_000) return d.toLocaleDateString([], { weekday: 'short' });
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  // ── Chat panel toggle ────────────────────────────────────────────────────

  toggleChat(): void {
    this.isChatOpen = !this.isChatOpen;
    if (this.isChatOpen) {
      setTimeout(() => this.scrollToBottom(), 60);
    }
  }

  // ── Superset embedding ───────────────────────────────────────────────────

  embedSuperset(): void {
    this.http.get<any>(`${environment.BACKEND_API_URL}/superset/sso-login`).subscribe({
      next: res => {
        const targetUrl = `/superset/dashboard/${res.dashboardId}/`;
        const url = `${environment.SUPERSET_DOMAIN}/login/custom?token=${res.token}&next=${encodeURIComponent(targetUrl)}`;
        this.supersetIframeUrl = this.sanitizer.bypassSecurityTrustResourceUrl(url);
      },
      error: err => console.error('Failed to load Superset SSO token', err)
    });
  }

  // ── Chat ─────────────────────────────────────────────────────────────────

  sendChat(): void {
    if (!this.chatQuery.trim() || this.isChatLoading) return;

    const userText = this.chatQuery.trim();
    this.messages.push({ text: userText, isUser: true });
    this.chatQuery = '';
    this.isChatLoading = true;
    this.scrollToBottom();

    this.http.post<any>(`${environment.BACKEND_API_URL}/chat/query`, {
      sessionId: this.sessionId,
      query: userText
    }).subscribe({
      next: res => {
        let reply: string = res.reply;

        const chartMatch = reply.match(/\[OPEN_CHART:(\d+)\]/);
        if (chartMatch) {
          reply = reply.replace(chartMatch[0], '').trim();
          this.navigateIframe(`/superset/explore/?slice_id=${chartMatch[1]}`);
        }

        const dashMatch = reply.match(/\[OPEN_DASHBOARD:(\d+)\]/);
        if (dashMatch) {
          reply = reply.replace(dashMatch[0], '').trim();
          this.navigateIframe(`/superset/dashboard/${dashMatch[1]}/`);
        }

        this.isChatLoading = false;
        this.pushAgentMessage(reply);
        this.saveSession();
        this.scrollToBottom();
      },
      error: () => {
        this.isChatLoading = false;
        this.pushAgentMessage('Connection error — please try again.');
        this.saveSession();
        this.scrollToBottom();
      }
    });
  }

  private navigateIframe(path: string): void {
    this.supersetIframeUrl = this.sanitizer.bypassSecurityTrustResourceUrl(
      `${environment.SUPERSET_DOMAIN}${path}`
    );
  }

  private pushAgentMessage(text: string): void {
    this.messages.push({ text, isUser: false, html: this.renderMarkdown(text) });
  }

  // ── Markdown renderer ────────────────────────────────────────────────────

  private renderMarkdown(raw: string): SafeHtml {
    let s = raw
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    s = s.replace(/```[^\n]*\n([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
    s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

    const lines = s.split('\n');
    const out: string[] = [];
    let inList = false;

    for (const line of lines) {
      const bullet = line.match(/^[\-\*]\s+(.*)/);
      const numbered = line.match(/^\d+\.\s+(.*)/);
      const listContent = bullet?.[1] ?? numbered?.[1] ?? null;

      if (listContent !== null) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push(`<li>${listContent}</li>`);
      } else {
        if (inList) { out.push('</ul>'); inList = false; }
        out.push(line.trim() === '' ? '<div class="md-gap"></div>' : `<div>${line}</div>`);
      }
    }
    if (inList) out.push('</ul>');

    return this.sanitizer.bypassSecurityTrustHtml(out.join(''));
  }

  // ── Utilities ────────────────────────────────────────────────────────────

  private scrollToBottom(): void {
    setTimeout(() => {
      if (this.chatScrollRef?.nativeElement) {
        this.chatScrollRef.nativeElement.scrollTop =
          this.chatScrollRef.nativeElement.scrollHeight;
      }
    }, 0);
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/login']);
  }
}
