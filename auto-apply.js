const axios = require('axios');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs');

// Configuration
const CONFIG = {
    maxApplicationsPerDay: 10,
    minDelayBetweenApplications: 300000, // 5 minutes
    resumePath: path.join(__dirname, 'resume.pdf'),
    coverLetterTemplate: path.join(__dirname, 'cover-letter-template.txt')
};

// Database connection
const db = new sqlite3.Database(path.join(__dirname, 'jobs.db'));

// Rate limiting
let lastApplicationTime = 0;
let applicationsToday = 0;
let lastResetDate = new Date().toDateString();

// Reset daily counter
function resetDailyCounter() {
    const today = new Date().toDateString();
    if (today !== lastResetDate) {
        applicationsToday = 0;
        lastResetDate = today;
    }
}

// Check if we can apply
function canApply() {
    resetDailyCounter();
    
    if (applicationsToday >= CONFIG.maxApplicationsPerDay) {
        console.log(`Daily limit reached (${CONFIG.maxApplicationsPerDay} applications)`);
        return false;
    }

    const timeSinceLastApplication = Date.now() - lastApplicationTime;
    if (timeSinceLastApplication < CONFIG.minDelayBetweenApplications) {
        const waitTime = Math.ceil((CONFIG.minDelayBetweenApplications - timeSinceLastApplication) / 1000);
        console.log(`Rate limit: Wait ${waitTime} seconds before next application`);
        return false;
    }

    return true;
}

// Load resume and cover letter
function loadApplicationMaterials() {
    let resume = null;
    let coverLetter = '';

    if (fs.existsSync(CONFIG.resumePath)) {
        resume = fs.readFileSync(CONFIG.resumePath);
    }

    if (fs.existsSync(CONFIG.coverLetterTemplate)) {
        coverLetter = fs.readFileSync(CONFIG.coverLetterTemplate, 'utf-8');
    }

    return { resume, coverLetter };
}

// Auto-apply to a job
async function autoApply(job, customCoverLetter = null) {
    if (!canApply()) {
        return { success: false, reason: 'Rate limit or daily limit reached' };
    }

    try {
        const { resume, coverLetter: defaultCoverLetter } = loadApplicationMaterials();
        const coverLetter = customCoverLetter || defaultCoverLetter;

        // This is a template - actual implementation depends on job board
        const applicationData = {
            jobId: job.id,
            jobTitle: job.title,
            company: job.company,
            resume: resume,
            coverLetter: coverLetter,
            personalInfo: {
                name: process.env.APPLICANT_NAME || 'Your Name',
                email: process.env.APPLICANT_EMAIL || 'your.email@example.com',
                phone: process.env.APPLICANT_PHONE || ''
            }
        };

        // Platform-specific application logic
        let result;
        if (job.source === 'RemoteOK') {
            result = await applyToRemoteOK(job, applicationData);
        } else if (job.source === 'WeWorkRemotely') {
            result = await applyToWeWorkRemotely(job, applicationData);
        } else if (job.source === 'Indeed') {
            result = await applyToIndeed(job, applicationData);
        } else {
            result = { success: false, reason: 'Platform not supported for auto-apply' };
        }

        if (result.success) {
            applicationsToday++;
            lastApplicationTime = Date.now();

            // Save to database
            db.run(
                'INSERT INTO applications (title, company, location, url, status, applied_date, notes) VALUES (?, ?, ?, ?, ?, ?, ?)',
                [job.title, job.company, job.location, job.url, 'applied', new Date().toISOString(), 'Auto-applied'],
                (err) => {
                    if (err) console.error('Database error:', err);
                }
            );

            console.log(`✅ Successfully applied to: ${job.title} at ${job.company}`);
        }

        return result;
    } catch (error) {
        console.error(`❌ Error applying to ${job.title}:`, error.message);
        return { success: false, reason: error.message };
    }
}

// Platform-specific application functions
async function applyToRemoteOK(job, applicationData) {
    // RemoteOK typically requires manual application
    // This would need to be customized based on their actual application process
    console.log(`⚠️  RemoteOK auto-apply not fully implemented. Manual application required for: ${job.url}`);
    return { success: false, reason: 'Manual application required', url: job.url };
}

async function applyToWeWorkRemotely(job, applicationData) {
    // Similar to RemoteOK - most job boards require manual application
    console.log(`⚠️  WeWorkRemotely auto-apply not fully implemented. Manual application required for: ${job.url}`);
    return { success: false, reason: 'Manual application required', url: job.url };
}

async function applyToIndeed(job, applicationData) {
    // Indeed has an API but requires authentication and specific setup
    console.log(`⚠️  Indeed auto-apply requires API authentication. Manual application required for: ${job.url}`);
    return { success: false, reason: 'API authentication required', url: job.url };
}

// Batch auto-apply
async function batchAutoApply(jobs, options = {}) {
    const {
        maxApplications = CONFIG.maxApplicationsPerDay,
        delay = CONFIG.minDelayBetweenApplications,
        filter = null
    } = options;

    const results = [];
    let applied = 0;

    for (const job of jobs) {
        if (applied >= maxApplications) {
            console.log(`Reached maximum applications (${maxApplications})`);
            break;
        }

        // Apply custom filter if provided
        if (filter && !filter(job)) {
            continue;
        }

        const result = await autoApply(job);
        results.push({ job, result });

        if (result.success) {
            applied++;
        }

        // Wait between applications
        if (applied < jobs.length - 1) {
            await new Promise(resolve => setTimeout(resolve, delay));
        }
    }

    return {
        total: jobs.length,
        applied,
        results
    };
}

// CLI interface
if (require.main === module) {
    const args = process.argv.slice(2);
    const command = args[0];

    if (command === 'apply') {
        const jobId = args[1];
        if (!jobId) {
            console.log('Usage: node auto-apply.js apply <job-id>');
            process.exit(1);
        }

        // Get job from database or API
        db.get('SELECT * FROM applications WHERE id = ?', [jobId], (err, job) => {
            if (err || !job) {
                console.error('Job not found');
                process.exit(1);
            }

            autoApply(job).then(result => {
                console.log(JSON.stringify(result, null, 2));
                process.exit(result.success ? 0 : 1);
            });
        });
    } else if (command === 'batch') {
        const maxApplications = parseInt(args[1]) || CONFIG.maxApplicationsPerDay;
        
        // Get jobs from database that haven't been applied to
        db.all('SELECT * FROM applications WHERE status = "pending" OR status IS NULL LIMIT ?', [maxApplications], (err, jobs) => {
            if (err) {
                console.error('Database error:', err);
                process.exit(1);
            }

            if (jobs.length === 0) {
                console.log('No pending jobs found');
                process.exit(0);
            }

            batchAutoApply(jobs, { maxApplications }).then(summary => {
                console.log('\n=== Auto-Apply Summary ===');
                console.log(`Total jobs: ${summary.total}`);
                console.log(`Applied: ${summary.applied}`);
                console.log(`Failed: ${summary.total - summary.applied}`);
                process.exit(0);
            });
        });
    } else {
        console.log(`
Auto-Apply Script for Job Search Platform

Usage:
  node auto-apply.js apply <job-id>    Apply to a specific job
  node auto-apply.js batch [max]       Batch apply to pending jobs

Configuration:
  Max applications per day: ${CONFIG.maxApplicationsPerDay}
  Min delay between applications: ${CONFIG.minDelayBetweenApplications / 1000}s

Note: Auto-apply functionality requires platform-specific API integrations.
Most job boards require manual application through their websites.
        `);
    }
}

module.exports = { autoApply, batchAutoApply, canApply };
