const express = require('express');
const cors = require('cors');
const axios = require('axios');
const cheerio = require('cheerio');
const nodemailer = require('nodemailer');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

// Database setup
const dbPath = path.join(__dirname, 'jobs.db');
const db = new sqlite3.Database(dbPath);

// Initialize database
db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        company TEXT,
        location TEXT,
        url TEXT,
        status TEXT,
        applied_date TEXT,
        notes TEXT,
        cover_letter TEXT,
        resume_version TEXT
    )`);

    db.run(`CREATE TABLE IF NOT EXISTS job_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        search_query TEXT,
        email TEXT,
        last_check TEXT,
        active INTEGER DEFAULT 1
    )`);

    db.run(`CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT UNIQUE,
        api_key TEXT,
        enabled INTEGER DEFAULT 1
    )`);
});

// Rate limiting
const rateLimit = new Map();
const RATE_LIMIT_WINDOW = 60000; // 1 minute
const MAX_REQUESTS = 10;

// URL validation - quick check if URL looks valid (without making request)
function isValidUrlFormat(url) {
    if (!url || typeof url !== 'string') return false;
    if (!url.startsWith('http://') && !url.startsWith('https://')) return false;
    // Filter out obvious dead link patterns
    if (url.includes('/410') || url.includes('/404') || url.includes('page-not-found')) return false;
    return true;
}

// URL validation - check if URL is still active (only for suspicious URLs)
async function validateJobUrl(url) {
    if (!isValidUrlFormat(url)) {
        return false;
    }
    
    // Skip validation for known good domains
    const trustedDomains = ['google.com', 'indeed.com', 'linkedin.com', 'wellfound.com', 'vibecoders.build', 'vibecodecareers.com', 'adaptify.ai'];
    if (trustedDomains.some(domain => url.includes(domain))) {
        return true; // Trust these domains
    }
    
    try {
        const response = await axios.head(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 3000, // Faster timeout
            maxRedirects: 3,
            validateStatus: (status) => status < 500 // Accept anything except 5xx
        });
        
        // Reject 410 (Gone) and 404 (Not Found)
        if (response.status === 410 || response.status === 404) {
            return false;
        }
        
        return true;
    } catch (error) {
        // If it's a 410/404 error, reject it
        if (error.response && (error.response.status === 410 || error.response.status === 404)) {
            return false;
        }
        // For other errors, assume it might be valid (network issues, etc.)
        return true;
    }
}

// Filter out invalid/outdated jobs
async function filterValidJobs(jobs) {
    if (!Array.isArray(jobs) || jobs.length === 0) {
        return [];
    }
    
    // First pass: filter by URL format
    const formatValidJobs = jobs.filter(job => {
        if (!job.url) return false;
        return isValidUrlFormat(job.url);
    });
    
    // Second pass: validate suspicious URLs (limit to 5 for performance)
    const suspiciousJobs = formatValidJobs.filter(job => {
        // Skip validation for search links and trusted domains
        if (job.note && (job.note.includes('Direct search link') || job.note.includes('Direct link'))) {
            return false; // Don't validate these
        }
        const trustedDomains = ['google.com', 'indeed.com', 'linkedin.com', 'wellfound.com'];
        if (trustedDomains.some(domain => job.url.includes(domain))) {
            return false; // Don't validate trusted domains
        }
        return true; // Needs validation
    });
    
    // Only validate first 5 suspicious jobs to avoid rate limiting
    const jobsToValidate = suspiciousJobs.slice(0, 5);
    const validationPromises = jobsToValidate.map(async (job) => {
        const isValid = await validateJobUrl(job.url);
        return isValid ? job : null;
    });
    
    const validatedResults = await Promise.allSettled(validationPromises);
    const validatedJobs = validatedResults
        .filter(result => result.status === 'fulfilled' && result.value !== null)
        .map(result => result.value);
    
    // Combine validated jobs with trusted jobs (search links, trusted domains, format-valid)
    const trustedJobs = formatValidJobs.filter(job => {
        if (job.note && (job.note.includes('Direct search link') || job.note.includes('Direct link'))) {
            return true;
        }
        const trustedDomains = ['google.com', 'indeed.com', 'linkedin.com', 'wellfound.com', 'vibecoders.build', 'vibecodecareers.com', 'adaptify.ai'];
        if (trustedDomains.some(domain => job.url.includes(domain))) {
            return true;
        }
        // If it wasn't in suspicious list, it's trusted
        return !suspiciousJobs.includes(job);
    });
    
    return [...validatedJobs, ...trustedJobs];
}

function checkRateLimit(ip) {
    const now = Date.now();
    const userRequests = rateLimit.get(ip) || { count: 0, resetTime: now + RATE_LIMIT_WINDOW };

    if (now > userRequests.resetTime) {
        userRequests.count = 0;
        userRequests.resetTime = now + RATE_LIMIT_WINDOW;
    }

    if (userRequests.count >= MAX_REQUESTS) {
        return false;
    }

    userRequests.count++;
    rateLimit.set(ip, userRequests);
    return true;
}

// Email configuration
function createEmailTransporter() {
    return nodemailer.createTransport({
        service: process.env.EMAIL_SERVICE || 'gmail',
        auth: {
            user: process.env.EMAIL_USER,
            pass: process.env.EMAIL_PASS
        }
    });
}

// Job Board API Integrations

// 1. RemoteOK API
async function searchRemoteOK(query, location = '') {
    try {
        const response = await axios.get('https://remoteok.com/api', {
            params: {
                tags: query.toLowerCase().includes('full stack') ? 'fullstack' : 
                      query.toLowerCase().includes('frontend') ? 'frontend' :
                      query.toLowerCase().includes('backend') ? 'backend' : 'dev',
                location: location || ''
            },
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 10000
        });

        if (Array.isArray(response.data) && response.data.length > 0) {
            return response.data.slice(0, 20).map(job => ({
                title: job.position || job.title || 'Developer',
                company: job.company || 'Unknown',
                location: 'Remote',
                description: job.description ? job.description.substring(0, 200) + '...' : 'No description available',
                url: `https://remoteok.com/remote-jobs/${job.id}`,
                tags: job.tags || [],
                salary: job.salary || '',
                date: job.date || new Date().toISOString(),
                source: 'RemoteOK'
            }));
        }
        return [];
    } catch (error) {
        console.error('RemoteOK API error:', error.message);
        return [];
    }
}

// 2. Web scraping for job boards (when APIs aren't available)
async function scrapeJobs(query, source = 'weworkremotely') {
    try {
        let url = '';
        if (source === 'weworkremotely') {
            url = `https://weworkremotely.com/categories/remote-programming-jobs`;
        } else if (source === 'stackoverflow') {
            url = `https://stackoverflow.com/jobs?q=${encodeURIComponent(query)}&l=Remote&d=20&u=Km`;
        }

        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        if (source === 'weworkremotely') {
            $('.feature').each((i, elem) => {
                if (i >= 20) return false;
                const title = $(elem).find('.title').text().trim();
                const company = $(elem).find('.company').text().trim();
                const link = $(elem).find('a').attr('href');
                
                if (title && company) {
                    jobs.push({
                        title,
                        company,
                        location: 'Remote',
                        description: 'Remote programming position',
                        url: `https://weworkremotely.com${link}`,
                        tags: [],
                        source: 'WeWorkRemotely'
                    });
                }
            });
        }

        return jobs;
    } catch (error) {
        console.error(`Scraping error (${source}):`, error.message);
        return [];
    }
}

// 3. LinkedIn Jobs (using search)
async function searchLinkedInJobs(query) {
    // Note: LinkedIn requires authentication for API access
    // This is a placeholder that would need LinkedIn API credentials
    try {
        // For now, return a search URL that users can visit
        return [{
            title: `Search LinkedIn for: ${query}`,
            company: 'LinkedIn',
            location: 'Remote',
            description: 'Visit LinkedIn Jobs to see available positions',
            url: `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(query)}&location=Remote&f_TPR=r86400`,
            tags: [],
            source: 'LinkedIn',
            note: 'Direct search link - LinkedIn API requires authentication'
        }];
    } catch (error) {
        console.error('LinkedIn search error:', error.message);
        return [];
    }
}

// 4. Indeed Jobs (scraping)
async function searchIndeedJobs(query, location = '') {
    try {
        const url = `https://www.indeed.com/jobs?q=${encodeURIComponent(query)}&l=${encodeURIComponent(location || 'Remote')}&radius=0&sort=date`;
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job_seen_beacon').each((i, elem) => {
            if (i >= 20) return false;
            const title = $(elem).find('.jobTitle a').text().trim();
            const company = $(elem).find('.companyName').text().trim();
            const locationText = $(elem).find('.companyLocation').text().trim();
            const link = $(elem).find('.jobTitle a').attr('href');
            
            // Check for job posting date to filter recent jobs
            const dateText = $(elem).find('.date').text().trim();
            const isRecent = !dateText || dateText.includes('day') || dateText.includes('hour') || dateText.includes('Just now');
            
            if (title && company && link) {
                // Only include if link looks valid (not a 410/404)
                const fullUrl = link.startsWith('http') ? link : `https://www.indeed.com${link}`;
                if (!fullUrl.includes('410') && !fullUrl.includes('404')) {
                    jobs.push({
                        title,
                        company,
                        location: locationText || 'Remote',
                        description: $(elem).find('.job-snippet').text().trim().substring(0, 200) + '...',
                        url: fullUrl,
                        tags: [],
                        source: 'Indeed',
                        date: dateText || 'Recent'
                    });
                }
            }
        });

        return jobs;
    } catch (error) {
        console.error('Indeed scraping error:', error.message);
        return [];
    }
}

// 5. Google Aggregator - Worldwide Aggregator (scraping)
async function searchGoogleJobs(query, location = '') {
    try {
        // Google Aggregator aggregates from many sources worldwide
        const searchQuery = `${query} ${location ? location + ' ' : ''}remote jobs`;
        const url = `https://www.google.com/search?q=${encodeURIComponent(searchQuery)}&ibp=htl;jobs`;
        
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5'
            },
            timeout: 20000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        // Google Aggregator structure - try multiple selectors
        $('[data-ved], .BjJfJf, .PwjeAc').each((i, elem) => {
            if (i >= 30) return false;
            
            const title = $(elem).find('h3, .BjJfJf, [role="heading"]').first().text().trim();
            const company = $(elem).find('.vNEEBe, .nJlQNd, .Qk80Jf').first().text().trim();
            const locationText = $(elem).find('.Qk80Jf, .sMzDsc').last().text().trim();
            const link = $(elem).find('a').first().attr('href');
            
            if (title && (company || link)) {
                let jobUrl = link;
                if (link && !link.startsWith('http')) {
                    jobUrl = `https://www.google.com${link}`;
                }
                
                jobs.push({
                    title: title || 'Job Opportunity',
                    company: company || 'Company',
                    location: locationText || location || 'Remote',
                    description: $(elem).find('.YgLbBe, .HBvzbc').text().trim().substring(0, 200) || 'Job opportunity via Google',
                    url: jobUrl || `https://www.google.com/search?q=${encodeURIComponent(searchQuery)}&ibp=htl;jobs`,
                    tags: [],
                    source: 'Google Aggregator',
                    note: 'Aggregated from multiple sources worldwide'
                });
            }
        });

        // Fallback: Return search link if no jobs found
        if (jobs.length === 0) {
            return [{
                title: `Google Aggregator Search: ${query}`,
                company: 'Multiple Employers',
                location: location || 'Worldwide',
                description: `Google Aggregator aggregates job listings from thousands of sources worldwide. Click to view all results.`,
                url: `https://www.google.com/search?q=${encodeURIComponent(searchQuery)}&ibp=htl;jobs`,
                tags: [],
                source: 'Google Aggregator',
                note: 'Direct search link - Google Aggregator aggregates from many sources'
            }];
        }

        return jobs.slice(0, 30);
    } catch (error) {
        console.error('Google Aggregator scraping error:', error.message);
        // Return search link as fallback
        const searchQuery = `${query} ${location ? location + ' ' : ''}remote jobs`;
        return [{
            title: `Google Jobs Search: ${query}`,
            company: 'Multiple Employers',
            location: location || 'Worldwide',
            description: `Google Jobs aggregates job listings from thousands of sources worldwide. Click to view all results.`,
            url: `https://www.google.com/search?q=${encodeURIComponent(searchQuery)}&ibp=htl;jobs`,
            tags: [],
            source: 'Google Jobs',
            note: 'Direct search link - Google Jobs aggregates from many sources'
        }];
    }
}

// 6. Stack Overflow Jobs
async function searchStackOverflowJobs(query, location = '') {
    try {
        const url = `https://stackoverflow.com/jobs?q=${encodeURIComponent(query)}&l=${encodeURIComponent(location || 'Remote')}&d=20&u=Km&sort=p`;
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.js-result, .-job').each((i, elem) => {
            if (i >= 20) return false;
            const title = $(elem).find('h2 a, .job-title a').text().trim();
            const company = $(elem).find('.employer, .-company').text().trim();
            const locationText = $(elem).find('.location, .-location').text().trim();
            const link = $(elem).find('h2 a, .job-title a').attr('href');
            
            if (title && company) {
                jobs.push({
                    title,
                    company,
                    location: locationText || 'Remote',
                    description: $(elem).find('.summary, .-job-summary').text().trim().substring(0, 200) + '...',
                    url: link && link.startsWith('http') ? link : `https://stackoverflow.com${link}`,
                    tags: $(elem).find('.post-tag, .-tag').map((i, el) => $(el).text()).get(),
                    source: 'Stack Overflow'
                });
            }
        });

        return jobs;
    } catch (error) {
        console.error('Stack Overflow scraping error:', error.message);
        return [];
    }
}

// 7. AngelList Jobs
async function searchAngelListJobs(query, location = '') {
    try {
        const url = `https://angel.co/jobs?roles[]=Developer&roles[]=Engineer&keywords=${encodeURIComponent(query)}`;
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job-listing, .job').each((i, elem) => {
            if (i >= 20) return false;
            const title = $(elem).find('.job-title, h3').text().trim();
            const company = $(elem).find('.company-name, .startup').text().trim();
            const link = $(elem).find('a').attr('href');
            
            if (title && company) {
                jobs.push({
                    title,
                    company,
                    location: 'Remote',
                    description: $(elem).find('.job-description, .description').text().trim().substring(0, 200) + '...',
                    url: link && link.startsWith('http') ? link : `https://angel.co${link}`,
                    tags: [],
                    source: 'AngelList'
                });
            }
        });

        return jobs;
    } catch (error) {
        console.error('AngelList scraping error:', error.message);
        return [];
    }
}

// 8. GitHub Jobs (via API)
async function searchGitHubJobs(query, location = '') {
    try {
        const url = `https://jobs.github.com/positions.json?description=${encodeURIComponent(query)}&location=${encodeURIComponent(location || 'remote')}`;
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        if (Array.isArray(response.data) && response.data.length > 0) {
            return response.data.slice(0, 20).map(job => ({
                title: job.title,
                company: job.company,
                location: job.location,
                description: job.description ? job.description.replace(/<[^>]*>/g, '').substring(0, 200) + '...' : 'No description',
                url: job.url,
                tags: job.type ? [job.type] : [],
                source: 'GitHub Jobs'
            }));
        }
        return [];
    } catch (error) {
        console.error('GitHub Jobs API error:', error.message);
        return [];
    }
}

// 9. FlexJobs (search link)
async function searchFlexJobs(query, location = '') {
    try {
        const searchQuery = `${query} ${location || 'remote'}`;
        return [{
            title: `FlexJobs Search: ${query}`,
            company: 'Multiple Employers',
            location: location || 'Remote',
            description: 'FlexJobs is a subscription-based job board specializing in remote and flexible work opportunities worldwide.',
            url: `https://www.flexjobs.com/search?search=${encodeURIComponent(searchQuery)}`,
            tags: [],
            source: 'FlexJobs',
            note: 'Direct search link - FlexJobs requires subscription for full access'
        }];
    } catch (error) {
        console.error('FlexJobs error:', error.message);
        return [];
    }
}

// 10. Remote.co Jobs
async function searchRemoteCoJobs(query, location = '') {
    try {
        const url = `https://remote.co/remote-jobs/${encodeURIComponent(query.toLowerCase().replace(/\s+/g, '-'))}/`;
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job_listing, .job-item').each((i, elem) => {
            if (i >= 20) return false;
            const title = $(elem).find('.job-title, h3').text().trim();
            const company = $(elem).find('.company-name, .company').text().trim();
            const link = $(elem).find('a').attr('href');
            
            if (title && company) {
                jobs.push({
                    title,
                    company,
                    location: 'Remote',
                    description: $(elem).find('.job-description, .description').text().trim().substring(0, 200) + '...',
                    url: link && link.startsWith('http') ? link : `https://remote.co${link}`,
                    tags: [],
                    source: 'Remote.co'
                });
            }
        });

        return jobs;
    } catch (error) {
        console.error('Remote.co scraping error:', error.message);
        return [];
    }
}

// 11. Remotive Jobs
async function searchRemotiveJobs(query, location = '') {
    try {
        const url = `https://remotive.io/remote-jobs/search?search=${encodeURIComponent(query)}`;
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job-tile, .job-item, [data-job-id]').each((i, elem) => {
            if (i >= 20) return false;
            const title = $(elem).find('.job-title, h3, .title').text().trim();
            const company = $(elem).find('.company-name, .company').text().trim();
            const link = $(elem).find('a').attr('href');
            
            if (title && company) {
                jobs.push({
                    title,
                    company,
                    location: 'Remote',
                    description: $(elem).find('.job-description, .description, .summary').text().trim().substring(0, 200) + '...',
                    url: link && link.startsWith('http') ? link : `https://remotive.io${link}`,
                    tags: [],
                    source: 'Remotive'
                });
            }
        });

        // Fallback: Return search link if no jobs found
        if (jobs.length === 0) {
            return [{
                title: `Remotive Search: ${query}`,
                company: 'Multiple Employers',
                location: 'Remote',
                description: 'Remotive is a remote jobs newsletter + job board. Great for coding, AI, and web dev roles.',
                url: `https://remotive.io/remote-jobs/search?search=${encodeURIComponent(query)}`,
                tags: [],
                source: 'Remotive',
                note: 'Direct search link - Remotive remote jobs board'
            }];
        }

        return jobs;
    } catch (error) {
        console.error('Remotive scraping error:', error.message);
        // Return search link as fallback
        return [{
            title: `Remotive Search: ${query}`,
            company: 'Multiple Employers',
            location: 'Remote',
            description: 'Remotive is a remote jobs newsletter + job board. Great for coding, AI, and web dev roles.',
            url: `https://remotive.io/remote-jobs/search?search=${encodeURIComponent(query)}`,
            tags: [],
            source: 'Remotive',
            note: 'Direct search link - Remotive remote jobs board'
        }];
    }
}

// 12. Just Remote Jobs
async function searchJustRemoteJobs(query, location = '') {
    try {
        const url = `https://justremote.co/remote-jobs/${encodeURIComponent(query.toLowerCase().replace(/\s+/g, '-'))}`;
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job-card, .job-item, [data-job]').each((i, elem) => {
            if (i >= 20) return false;
            const title = $(elem).find('.job-title, h3, .title').text().trim();
            const company = $(elem).find('.company-name, .company').text().trim();
            const link = $(elem).find('a').attr('href');
            
            if (title && company) {
                jobs.push({
                    title,
                    company,
                    location: 'Remote',
                    description: $(elem).find('.job-description, .description, .summary').text().trim().substring(0, 200) + '...',
                    url: link && link.startsWith('http') ? link : `https://justremote.co${link}`,
                    tags: [],
                    source: 'Just Remote'
                });
            }
        });

        // Fallback: Return search link if no jobs found
        if (jobs.length === 0) {
            return [{
                title: `Just Remote Search: ${query}`,
                company: 'Multiple Employers',
                location: 'Remote',
                description: 'Just Remote offers remote-only jobs for devs, designers, and product managers.',
                url: `https://justremote.co/remote-jobs/${encodeURIComponent(query.toLowerCase().replace(/\s+/g, '-'))}`,
                tags: [],
                source: 'Just Remote',
                note: 'Direct search link - Just Remote remote jobs board'
            }];
        }

        return jobs;
    } catch (error) {
        console.error('Just Remote scraping error:', error.message);
        // Return search link as fallback
        return [{
            title: `Just Remote Search: ${query}`,
            company: 'Multiple Employers',
            location: 'Remote',
            description: 'Just Remote offers remote-only jobs for devs, designers, and product managers.',
            url: `https://justremote.co/remote-jobs/${encodeURIComponent(query.toLowerCase().replace(/\s+/g, '-'))}`,
            tags: [],
            source: 'Just Remote',
            note: 'Direct search link - Just Remote remote jobs board'
        }];
    }
}

// 13. Vibe Coders Job Board
async function searchVibeCodersJobs(query, location = '') {
    try {
        const url = 'https://www.vibecoders.build/jobs';
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job-listing, .job-card, .job-item, [data-job]').each((i, elem) => {
            if (i >= 30) return false;
            const title = $(elem).find('.job-title, h3, h2, .title').text().trim();
            const company = $(elem).find('.company-name, .company').text().trim();
            const link = $(elem).find('a').attr('href');
            
            if (title) {
                jobs.push({
                    title: title || 'Vibe Coder Position',
                    company: company || 'Various Companies',
                    location: 'Remote',
                    description: $(elem).find('.job-description, .description, .summary').text().trim().substring(0, 200) + '...' || 'Vibe Coding role - Browse for details',
                    url: link && link.startsWith('http') ? link : `https://www.vibecoders.build${link || '/jobs'}`,
                    tags: ['Vibe Coder', 'Remote'],
                    source: 'Vibe Coders'
                });
            }
        });

        // Fallback: Return direct link to job board
        if (jobs.length === 0) {
            return [{
                title: 'Vibe Coders Job Board',
                company: 'Multiple Employers',
                location: 'Remote',
                description: 'Browse and apply for various Vibe Coding roles (remote/full-time/contract). Multiple open positions available.',
                url: 'https://www.vibecoders.build/jobs',
                tags: ['Vibe Coder', 'Remote'],
                source: 'Vibe Coders',
                note: 'Direct link to Vibe Coders job board'
            }];
        }

        return jobs;
    } catch (error) {
        console.error('Vibe Coders scraping error:', error.message);
        return [{
            title: 'Vibe Coders Job Board',
            company: 'Multiple Employers',
            location: 'Remote',
            description: 'Browse and apply for various Vibe Coding roles (remote/full-time/contract). Multiple open positions available.',
            url: 'https://www.vibecoders.build/jobs',
            tags: ['Vibe Coder', 'Remote'],
            source: 'Vibe Coders',
            note: 'Direct link to Vibe Coders job board'
        }];
    }
}

// 14. Vibe Code Careers
async function searchVibeCodeCareersJobs(query, location = '') {
    try {
        const url = 'https://www.vibecodecareers.com/jobs/';
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job-listing, .job-card, .job-item, [data-job]').each((i, elem) => {
            if (i >= 30) return false;
            const title = $(elem).find('.job-title, h3, h2, .title').text().trim();
            const company = $(elem).find('.company-name, .company').text().trim();
            const link = $(elem).find('a').attr('href');
            
            if (title) {
                jobs.push({
                    title: title || 'AI-Fluent Vibe Coder',
                    company: company || 'Various Companies',
                    location: 'Remote',
                    description: $(elem).find('.job-description, .description, .summary').text().trim().substring(0, 200) + '...' || 'AI-native developer role - Good for remote AI-fluent vibe coding positions',
                    url: link && link.startsWith('http') ? link : `https://www.vibecodecareers.com${link || '/jobs/'}`,
                    tags: ['Vibe Coder', 'AI', 'Remote'],
                    source: 'Vibe Code Careers'
                });
            }
        });

        // Fallback: Return direct link
        if (jobs.length === 0) {
            return [{
                title: 'AI-Fluent Vibe Coding Jobs',
                company: 'Multiple Employers',
                location: 'Remote',
                description: 'Listings including Game Developer – Vibe Coder. Good for remote AI-native developer roles.',
                url: 'https://www.vibecodecareers.com/jobs/',
                tags: ['Vibe Coder', 'AI', 'Remote'],
                source: 'Vibe Code Careers',
                note: 'Direct link to AI-Fluent Vibe Coding jobs'
            }];
        }

        return jobs;
    } catch (error) {
        console.error('Vibe Code Careers scraping error:', error.message);
        return [{
            title: 'AI-Fluent Vibe Coding Jobs',
            company: 'Multiple Employers',
            location: 'Remote',
            description: 'Listings including Game Developer – Vibe Coder. Good for remote AI-native developer roles.',
            url: 'https://www.vibecodecareers.com/jobs/',
            tags: ['Vibe Coder', 'AI', 'Remote'],
            source: 'Vibe Code Careers',
            note: 'Direct link to AI-Fluent Vibe Coding jobs'
        }];
    }
}

// 15. Wellfound (formerly AngelList)
async function searchWellfoundJobs(query, location = '') {
    try {
        // Wellfound specific vibe coder listings
        const vibeCoderJobs = [
            {
                title: 'Vibe Coder',
                company: 'Quell',
                location: 'Remote + US',
                description: 'Vibe Coder position hiring now. Remote work available with locations in US.',
                url: 'https://wellfound.com/jobs/3378044-vibe-coder',
                tags: ['Vibe Coder', 'Remote'],
                source: 'Wellfound'
            },
            {
                title: 'Game Developer – Vibe Coder',
                company: 'Timedrift',
                location: 'Remote',
                description: 'Creative/AI-augmented game maker role. Remote position for vibe coders.',
                url: 'https://wellfound.com/jobs/3332731-game-developer-vibe-coder',
                tags: ['Vibe Coder', 'Game Developer', 'AI', 'Remote'],
                source: 'Wellfound'
            }
        ];

        // Also try general Wellfound search
        const url = `https://wellfound.com/jobs?keywords=${encodeURIComponent(query + ' vibe coder')}`;
        try {
            const response = await axios.get(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                timeout: 15000
            });

            const $ = cheerio.load(response.data);
            $('.job-card, .job-listing').each((i, elem) => {
                if (i >= 10) return false;
                const title = $(elem).find('.job-title, h3').text().trim();
                const company = $(elem).find('.company-name, .company').text().trim();
                const link = $(elem).find('a').attr('href');
                
                if (title && (title.toLowerCase().includes('vibe') || title.toLowerCase().includes('coder'))) {
                    vibeCoderJobs.push({
                        title,
                        company: company || 'Startup',
                        location: 'Remote',
                        description: $(elem).find('.job-description, .summary').text().trim().substring(0, 200) + '...',
                        url: link && link.startsWith('http') ? link : `https://wellfound.com${link}`,
                        tags: ['Vibe Coder'],
                        source: 'Wellfound'
                    });
                }
            });
        } catch (err) {
            console.log('Wellfound search fallback to specific listings');
        }

        return vibeCoderJobs.length > 0 ? vibeCoderJobs : [{
            title: 'Wellfound Vibe Coder Jobs',
            company: 'Multiple Startups',
            location: 'Remote',
            description: 'Browse vibe coder positions on Wellfound. Includes specific roles at Quell and Timedrift.',
            url: `https://wellfound.com/jobs?keywords=${encodeURIComponent(query + ' vibe coder')}`,
            tags: ['Vibe Coder', 'Remote'],
            source: 'Wellfound',
            note: 'Direct link to Wellfound vibe coder jobs'
        }];
    } catch (error) {
        console.error('Wellfound scraping error:', error.message);
        return [{
            title: 'Wellfound Vibe Coder Jobs',
            company: 'Multiple Startups',
            location: 'Remote',
            description: 'Browse vibe coder positions on Wellfound. Includes specific roles at Quell and Timedrift.',
            url: `https://wellfound.com/jobs?keywords=${encodeURIComponent(query + ' vibe coder')}`,
            tags: ['Vibe Coder', 'Remote'],
            source: 'Wellfound',
            note: 'Direct link to Wellfound vibe coder jobs'
        }];
    }
}

// 16. Adaptify Jobs
async function searchAdaptifyJobs(query, location = '') {
    try {
        const url = 'https://www.adaptify.ai/jobs/vibe-coder';
        const response = await axios.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout: 15000
        });

        const $ = cheerio.load(response.data);
        const jobs = [];

        $('.job-listing, .job-card, .job-detail, [data-job]').each((i, elem) => {
            if (i >= 10) return false;
            const title = $(elem).find('.job-title, h1, h2, h3, .title').text().trim();
            const company = 'Adaptify SEO';
            const link = $(elem).find('a').attr('href');
            
            if (title || i === 0) {
                jobs.push({
                    title: title || 'Vibe Coder',
                    company: company,
                    location: 'Remote',
                    description: $(elem).find('.job-description, .description, .content').text().trim().substring(0, 200) + '...' || 'A vibe coder position focused on AI + full-stack development',
                    url: link && link.startsWith('http') ? link : 'https://www.adaptify.ai/jobs/vibe-coder',
                    tags: ['Vibe Coder', 'AI', 'Full Stack', 'Remote'],
                    source: 'Adaptify'
                });
            }
        });

        // Fallback: Return direct link
        if (jobs.length === 0) {
            return [{
                title: 'Vibe Coder - Adaptify SEO',
                company: 'Adaptify SEO',
                location: 'Remote',
                description: 'A vibe coder position focused on AI + full-stack development. Remote work available.',
                url: 'https://www.adaptify.ai/jobs/vibe-coder',
                tags: ['Vibe Coder', 'AI', 'Full Stack', 'Remote'],
                source: 'Adaptify',
                note: 'Direct link to Adaptify vibe coder position'
            }];
        }

        return jobs;
    } catch (error) {
        console.error('Adaptify scraping error:', error.message);
        return [{
            title: 'Vibe Coder - Adaptify SEO',
            company: 'Adaptify SEO',
            location: 'Remote',
            description: 'A vibe coder position focused on AI + full-stack development. Remote work available.',
            url: 'https://www.adaptify.ai/jobs/vibe-coder',
            tags: ['Vibe Coder', 'AI', 'Full Stack', 'Remote'],
            source: 'Adaptify',
            note: 'Direct link to Adaptify vibe coder position'
        }];
    }
}

// Main job search endpoint
app.post('/api/jobs/search', async (req, res) => {
    if (!checkRateLimit(req.ip)) {
        return res.status(429).json({ error: 'Rate limit exceeded. Please wait a minute.' });
    }

    try {
        const { query, location, sources } = req.body;
        
        if (!query) {
            return res.status(400).json({ error: 'Query is required' });
        }

        const searchPromises = [];
        // Default sources - prioritize vibe coder sources if query suggests it
        const defaultSources = query.toLowerCase().includes('vibe') || query.toLowerCase().includes('ai-assisted') || query.toLowerCase().includes('cursor')
            ? ['google', 'vibecoders', 'vibecodecareers', 'wellfound', 'adaptify', 'remoteok', 'indeed']
            : ['google', 'remoteok', 'weworkremotely', 'indeed', 'stackoverflow', 'github', 'angellist'];
        const requestedSources = sources || defaultSources;

        // Google Aggregator - Worldwide aggregator (always include if not explicitly excluded)
        if (requestedSources.includes('google') || requestedSources.length === 0) {
            searchPromises.push(searchGoogleJobs(query, location));
        }
        if (requestedSources.includes('remoteok')) {
            searchPromises.push(searchRemoteOK(query, location));
        }
        if (requestedSources.includes('weworkremotely')) {
            searchPromises.push(scrapeJobs(query, 'weworkremotely'));
        }
        if (requestedSources.includes('indeed')) {
            searchPromises.push(searchIndeedJobs(query, location));
        }
        if (requestedSources.includes('linkedin')) {
            searchPromises.push(searchLinkedInJobs(query));
        }
        if (requestedSources.includes('stackoverflow')) {
            searchPromises.push(searchStackOverflowJobs(query, location));
        }
        if (requestedSources.includes('github')) {
            searchPromises.push(searchGitHubJobs(query, location));
        }
        if (requestedSources.includes('angellist')) {
            searchPromises.push(searchAngelListJobs(query, location));
        }
        if (requestedSources.includes('flexjobs')) {
            searchPromises.push(searchFlexJobs(query, location));
        }
        if (requestedSources.includes('remoteco')) {
            searchPromises.push(searchRemoteCoJobs(query, location));
        }
        if (requestedSources.includes('remotive')) {
            searchPromises.push(searchRemotiveJobs(query, location));
        }
        if (requestedSources.includes('justremote')) {
            searchPromises.push(searchJustRemoteJobs(query, location));
        }
        if (requestedSources.includes('vibecoders')) {
            searchPromises.push(searchVibeCodersJobs(query, location));
        }
        if (requestedSources.includes('vibecodecareers')) {
            searchPromises.push(searchVibeCodeCareersJobs(query, location));
        }
        if (requestedSources.includes('wellfound')) {
            searchPromises.push(searchWellfoundJobs(query, location));
        }
        if (requestedSources.includes('adaptify')) {
            searchPromises.push(searchAdaptifyJobs(query, location));
        }

        const results = await Promise.allSettled(searchPromises);
        const allJobs = [];

        results.forEach(result => {
            if (result.status === 'fulfilled') {
                allJobs.push(...result.value);
            }
        });

        // Remove duplicates based on title and company
        const uniqueJobs = [];
        const seen = new Set();
        allJobs.forEach(job => {
            const key = `${job.title}-${job.company}`;
            if (!seen.has(key)) {
                seen.add(key);
                uniqueJobs.push(job);
            }
        });

        // Filter out invalid/outdated URLs
        const finalJobs = await filterValidJobs(uniqueJobs);
        
        // Sort by source priority (prefer actual job listings over search links)
        finalJobs.sort((a, b) => {
            // Search links go to bottom
            if (a.note && !b.note) return 1;
            if (!a.note && b.note) return -1;
            // Prioritize recent jobs if date available
            if (a.date && b.date) {
                return 0; // Keep original order
            }
            return 0;
        });

        // Ensure all jobs have required fields before sending
        const normalizedJobs = finalJobs.map(job => {
            return {
                title: job.title || 'Job Opportunity',
                company: job.company || 'Company',
                location: job.location || 'Remote',
                description: job.description || 'No description available',
                url: job.url || '#',
                source: job.source || 'Unknown',
                tags: Array.isArray(job.tags) ? job.tags : [],
                note: job.note || null,
                date: job.date || null
            };
        });

        res.json({ jobs: normalizedJobs, count: normalizedJobs.length });
    } catch (error) {
        console.error('Job search error:', error);
        res.status(500).json({ error: 'Failed to search jobs', message: error.message });
    }
});

// Application tracking endpoints
app.get('/api/applications', (req, res) => {
    db.all('SELECT * FROM applications ORDER BY applied_date DESC', (err, rows) => {
        if (err) {
            return res.status(500).json({ error: err.message });
        }
        res.json(rows);
    });
});

app.post('/api/applications', (req, res) => {
    const { title, company, location, url, notes, cover_letter, resume_version } = req.body;
    const status = req.body.status || 'applied';
    const applied_date = new Date().toISOString();

    db.run(
        'INSERT INTO applications (title, company, location, url, status, applied_date, notes, cover_letter, resume_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [title, company, location, url, status, applied_date, notes, cover_letter, resume_version],
        function(err) {
            if (err) {
                return res.status(500).json({ error: err.message });
            }
            res.json({ id: this.lastID, message: 'Application saved' });
        }
    );
});

app.put('/api/applications/:id', (req, res) => {
    const { status, notes } = req.body;
    db.run(
        'UPDATE applications SET status = ?, notes = ? WHERE id = ?',
        [status, notes, req.params.id],
        function(err) {
            if (err) {
                return res.status(500).json({ error: err.message });
            }
            res.json({ message: 'Application updated' });
        }
    );
});

app.delete('/api/applications/:id', (req, res) => {
    db.run('DELETE FROM applications WHERE id = ?', [req.params.id], function(err) {
        if (err) {
            return res.status(500).json({ error: err.message });
        }
        res.json({ message: 'Application deleted' });
    });
});

// Resume generator endpoint
app.post('/api/resume/generate', (req, res) => {
    const { personalInfo, experience, skills, education, projects, aiTools } = req.body;

    const resume = {
        personal: personalInfo,
        summary: `Full-stack developer with expertise in modern web technologies and AI-assisted development. Experienced in building scalable applications using cutting-edge tools and frameworks.`,
        experience: experience || [],
        skills: skills || [],
        education: education || [],
        projects: projects || [],
        aiTools: aiTools || ['Cursor AI', 'GitHub Copilot', 'ChatGPT'],
        generatedAt: new Date().toISOString()
    };

    res.json({ resume, pdf: null }); // PDF generation would require additional library
});

// Cover letter generator
app.post('/api/cover-letter/generate', (req, res) => {
    const { jobTitle, companyName, jobDescription, personalInfo, relevantExperience } = req.body;

    const coverLetter = `Dear Hiring Manager,

I am writing to express my interest in the ${jobTitle} position at ${companyName}. As a full-stack developer with extensive experience in AI-assisted development, I am excited about the opportunity to contribute to your team.

${jobDescription ? `I noticed that this role requires ${jobDescription.substring(0, 100)}...` : 'This role aligns perfectly with my skills and experience.'}

With over 10 projects completed in the past 6 months using modern AI development tools, I bring a unique combination of technical expertise and efficient development practices. My experience includes:

${relevantExperience ? relevantExperience.map(exp => `• ${exp}`).join('\n') : '• Full-stack web development\n• Mobile app development\n• AI model integration\n• Automation and workflow optimization'}

I am particularly drawn to ${companyName} because of ${personalInfo?.whyCompany || 'your innovative approach to technology and commitment to excellence'}.

I would welcome the opportunity to discuss how my skills in AI-assisted development can contribute to your team's success. Thank you for considering my application.

Best regards,
${personalInfo?.name || 'Your Name'}`;

    res.json({ coverLetter });
});

// Email notifications
app.post('/api/alerts/create', (req, res) => {
    const { search_query, email } = req.body;

    db.run(
        'INSERT INTO job_alerts (search_query, email, last_check, active) VALUES (?, ?, ?, 1)',
        [search_query, email, new Date().toISOString()],
        function(err) {
            if (err) {
                return res.status(500).json({ error: err.message });
            }
            res.json({ id: this.lastID, message: 'Alert created' });
        }
    );
});

app.post('/api/alerts/check', async (req, res) => {
    try {
        db.all('SELECT * FROM job_alerts WHERE active = 1', async (err, alerts) => {
            if (err) {
                return res.status(500).json({ error: err.message });
            }

            const results = [];
            for (const alert of alerts) {
                const jobs = await searchRemoteOK(alert.search_query);
                const newJobs = jobs.filter(job => {
                    // Check if job is new (simplified - in production, store job IDs)
                    return true;
                });

                if (newJobs.length > 0 && alert.email) {
                    try {
                        const transporter = createEmailTransporter();
                        await transporter.sendMail({
                            from: process.env.EMAIL_USER,
                            to: alert.email,
                            subject: `New Jobs Found: ${alert.search_query}`,
                            html: `
                                <h2>New Job Opportunities</h2>
                                ${newJobs.map(job => `
                                    <div style="margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px;">
                                        <h3>${job.title}</h3>
                                        <p><strong>Company:</strong> ${job.company}</p>
                                        <p><strong>Location:</strong> ${job.location}</p>
                                        <a href="${job.url}" style="display: inline-block; margin-top: 10px; padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px;">View Job</a>
                                    </div>
                                `).join('')}
                            `
                        });
                        results.push({ alert: alert.id, jobsFound: newJobs.length });
                    } catch (emailError) {
                        console.error('Email error:', emailError);
                    }
                }

                // Update last check
                db.run('UPDATE job_alerts SET last_check = ? WHERE id = ?', 
                    [new Date().toISOString(), alert.id]);
            }

            res.json({ message: 'Alerts checked', results });
        });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Auto-apply endpoint (with rate limiting)
app.post('/api/auto-apply', async (req, res) => {
    if (!checkRateLimit(req.ip)) {
        return res.status(429).json({ error: 'Rate limit exceeded' });
    }

    const { jobId, coverLetter, resume } = req.body;
    
    // Note: Auto-applying requires specific integration with each job board
    // This is a placeholder that would need to be customized per platform
    res.json({ 
        message: 'Auto-apply feature requires platform-specific integration',
        note: 'This would need to be implemented per job board API requirements'
    });
});

// Health check
app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.listen(PORT, () => {
    console.log(`Job Search API running on port ${PORT}`);
});
