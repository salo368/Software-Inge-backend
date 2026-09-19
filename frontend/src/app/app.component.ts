import { Component, VERSION } from '@angular/core';
import { environment } from '../environments/environment';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent {
  readonly stage = environment.stage;
  readonly angularVersion = VERSION.full;
  readonly buildTime = new Date().toISOString();
}
