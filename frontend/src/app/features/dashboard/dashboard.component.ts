import { Component, OnInit, AfterViewInit, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { AuthService } from '../../core/services/auth.service';
import { environment } from '../../../environments/environment';
import { embedDashboard } from '@superset-ui/embedded-sdk';

interface ChatMessage {
  text: string;
  isUser: boolean;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.css']
})
export class DashboardComponent implements OnInit, AfterViewInit {
  @Input() username: string = '';
  @Input() role: string = '';
  sessionId: string = crypto.randomUUID();
  chatQuery: string = '';
  messages: ChatMessage[] = [
    { text: 'Hello! I am your AI Data Agent. I can query the market data while respecting your access level. How can I help you today?', isUser: false }
  ];
  isChatLoading: boolean = false;

  constructor(private authService: AuthService, private router: Router, private http: HttpClient) {}

  ngOnInit() {
    if (!this.authService.isAuthenticated()) {
      this.router.navigate(['/login']);
      return;
    }
    
    const token = this.authService.getToken();
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        this.username = payload.sub || 'User';
      } catch (e) {
        this.username = 'User';
      }
    }
  }

  ngAfterViewInit() {
    this.embedSuperset();
  }

  embedSuperset() {
    this.http.get<any>(`${environment.BACKEND_API_URL}/superset/guest-token`).subscribe({
      next: (res) => {
        const token = res.token;
        const dashboardId = res.dashboardId;
        const mountPoint = document.getElementById('dashboard-mount-point');
        if (mountPoint && dashboardId) {
            mountPoint.innerHTML = '';
            // Clear the Superset session cookie to prevent conflict with the Guest Token on refresh
            document.cookie = "session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
            embedDashboard({
                id: dashboardId,
                supersetDomain: environment.SUPERSET_DOMAIN,
                mountPoint: mountPoint,
                fetchGuestToken: () => Promise.resolve(token),
                dashboardUiConfig: { hideTitle: true, hideChartControls: true, hideTab: true }
            });
        }
      },
      error: (err) => console.error("Failed to load Superset guest token", err)
    });
  }

  sendChat() {
    if (!this.chatQuery.trim()) return;
    
    const userText = this.chatQuery;
    this.messages.push({ text: userText, isUser: true });
    this.chatQuery = '';
    this.isChatLoading = true;

    this.http.post<any>(`${environment.BACKEND_API_URL}/chat/query`, {
      sessionId: this.sessionId,
      query: userText
    }).subscribe({
      next: (res) => {
        this.messages.push({ text: res.reply, isUser: false });
        this.isChatLoading = false;
      },
      error: (err) => {
        this.messages.push({ text: 'Error connecting to Data Agent.', isUser: false });
        this.isChatLoading = false;
      }
    });
  }

  logout() {
    this.authService.logout();
    this.router.navigate(['/login']);
  }
}
