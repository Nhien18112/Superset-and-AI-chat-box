import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private baseUrl = environment.BACKEND_API_URL;

  constructor(private http: HttpClient) {}

  getGuestToken(username: string, role: string, dashboardId: string): Observable<{token: string}> {
    return this.http.get<{token: string}>(`${this.baseUrl}/superset/guest-token`, {
      params: { username, role, dashboardId }
    });
  }

  sendChatQuery(message: string, username: string, role: string): Observable<any> {
    return this.http.post<any>(`${this.baseUrl}/chat/query`, {
      message, username, role
    });
  }
}
