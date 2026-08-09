# Job Search Platform Setup Guide

Complete setup instructions for the Remote Job Search Platform for Vibe Coders.

## Prerequisites

- Node.js (v14 or higher)
- npm or yarn
- SQLite3 (usually included with Node.js)
- Email account for job alerts (Gmail recommended)

## Installation

1. **Install dependencies:**
```bash
cd job-search
npm install
```

2. **Configure environment variables:**
Create a `.env` file in the `job-search` directory:

```env
# Server Configuration
PORT=3001

# Email Configuration (for job alerts)
EMAIL_SERVICE=gmail
EMAIL_USER=your-email@gmail.com
EMAIL_PASS=your-app-password

# Applicant Information (for auto-apply)
APPLICANT_NAME=Your Name
APPLICANT_EMAIL=your.email@example.com
APPLICANT_PHONE=+1 (555) 123-4567

# API Keys (optional, for enhanced features)
LINKEDIN_API_KEY=
INDEED_API_KEY=
REMOTEOK_API_KEY=
```

### Gmail Setup for Email Alerts

1. Go to your Google Account settings
2. Enable 2-Step Verification
3. Generate an App Password:
   - Go to: https://myaccount.google.com/apppasswords
   - Select "Mail" and "Other (Custom name)"
   - Enter "Job Search Platform"
   - Copy the generated password
   - Use this password in `EMAIL_PASS` in your `.env` file

## Running the Platform

### Development Mode

```bash
npm run dev
```

### Production Mode

```bash
npm start
```

The server will start on `http://localhost:3001`

## Accessing the Dashboard

Open `http://localhost:3001` in your browser to access the job search dashboard.

## Features

### 1. Job Search
- Search across multiple job boards (RemoteOK, WeWorkRemotely, Indeed)
- Filter by role type, location, and more
- Real-time job listings

### 2. Application Tracker
- Track all your job applications
- Update application status
- Add notes and reminders

### 3. Resume Builder
- Generate professional resumes
- Tailored for AI-assisted developers
- Export as text (PDF export can be added)

### 4. Cover Letter Generator
- Customize cover letters per job
- AI-assisted template generation
- Quick copy to clipboard

### 5. Job Alerts
- Set up email alerts for new job postings
- Automatic daily checks
- Email notifications with job links

### 6. Auto-Apply (Advanced)
```bash
# Apply to a specific job
node auto-apply.js apply <job-id>

# Batch apply to pending jobs
node auto-apply.js batch [max-applications]
```

**Note:** Auto-apply requires platform-specific API integrations. Most job boards require manual application through their websites.

## API Endpoints

- `POST /api/jobs/search` - Search for jobs
- `GET /api/applications` - Get all applications
- `POST /api/applications` - Save new application
- `PUT /api/applications/:id` - Update application
- `DELETE /api/applications/:id` - Delete application
- `POST /api/resume/generate` - Generate resume
- `POST /api/cover-letter/generate` - Generate cover letter
- `POST /api/alerts/create` - Create job alert
- `POST /api/alerts/check` - Check for new jobs (manual trigger)
- `GET /api/health` - Health check

## Database

The platform uses SQLite3. The database file (`jobs.db`) is created automatically in the `job-search` directory.

### Database Schema

**applications:**
- id, title, company, location, url, status, applied_date, notes, cover_letter, resume_version

**job_alerts:**
- id, search_query, email, last_check, active

**api_keys:**
- id, service, api_key, enabled

## Deployment

### Apache2 Configuration

1. **Install Apache2:**
```bash
sudo apt update
sudo apt install apache2
```

2. **Enable mod_proxy:**
```bash
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo a2enmod rewrite
```

3. **Create Apache configuration:**
Create `/etc/apache2/sites-available/job-search.conf`:

```apache
<VirtualHost *:80>
    ServerName your-domain.com
    ServerAlias www.your-domain.com

    ProxyPreserveHost On
    ProxyPass / http://localhost:3001/
    ProxyPassReverse / http://localhost:3001/

    ErrorLog ${APACHE_LOG_DIR}/job-search-error.log
    CustomLog ${APACHE_LOG_DIR}/job-search-access.log combined
</VirtualHost>
```

4. **Enable site:**
```bash
sudo a2ensite job-search.conf
sudo systemctl reload apache2
```

### SSL Setup with Let's Encrypt

1. **Install Certbot:**
```bash
sudo apt install certbot python3-certbot-apache
```

2. **Get SSL certificate:**
```bash
sudo certbot --apache -d your-domain.com -d www.your-domain.com
```

3. **Auto-renewal (already configured):**
```bash
sudo certbot renew --dry-run
```

### PM2 for Process Management

1. **Install PM2:**
```bash
npm install -g pm2
```

2. **Start application:**
```bash
cd /path/to/job-search
pm2 start server.js --name job-search
pm2 save
pm2 startup
```

3. **PM2 commands:**
```bash
pm2 list              # List all processes
pm2 logs job-search    # View logs
pm2 restart job-search # Restart
pm2 stop job-search    # Stop
```

## Troubleshooting

### API Connection Issues
- Ensure the server is running on port 3001
- Check firewall settings
- Verify CORS configuration

### Email Not Sending
- Verify Gmail app password is correct
- Check email service settings in `.env`
- Review server logs for email errors

### Job Search Not Working
- Some job boards may block automated requests
- Check rate limiting settings
- Verify API keys if using premium features

### Database Errors
- Ensure SQLite3 is installed
- Check file permissions on `jobs.db`
- Verify database schema is correct

## Security Notes

- Never commit `.env` file to version control
- Use strong passwords for email accounts
- Regularly update dependencies
- Keep API keys secure
- Use HTTPS in production
- Implement proper authentication if sharing the platform

## Support

For issues or questions, check:
- Server logs: `pm2 logs job-search`
- Apache logs: `/var/log/apache2/`
- Browser console for frontend errors

## Next Steps

1. Customize resume and cover letter templates
2. Add more job board integrations
3. Implement user authentication
4. Add PDF export for resumes
5. Set up automated daily job checks
6. Add analytics and reporting
