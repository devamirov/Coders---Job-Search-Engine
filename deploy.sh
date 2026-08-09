#!/bin/bash

# Job Search Platform Deployment Script
# This script helps deploy the platform to a server with Apache2 and SSL

set -e

echo "🚀 Job Search Platform Deployment Script"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root for system commands
if [ "$EUID" -ne 0 ]; then 
    echo -e "${YELLOW}Note: Some commands require sudo. You may be prompted for your password.${NC}"
fi

# Get deployment directory
read -p "Enter the deployment directory path (e.g., /var/www/job-search): " DEPLOY_DIR
if [ -z "$DEPLOY_DIR" ]; then
    DEPLOY_DIR="/var/www/job-search"
fi

# Get domain name
read -p "Enter your domain name (e.g., jobs.yourdomain.com): " DOMAIN
if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Domain name is required!${NC}"
    exit 1
fi

# Get port (default 3001)
read -p "Enter the port for the Node.js server (default: 3001): " PORT
PORT=${PORT:-3001}

echo ""
echo -e "${GREEN}Starting deployment...${NC}"
echo ""

# Step 1: Install dependencies
echo "📦 Step 1: Installing Node.js dependencies..."
npm install
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Step 2: Create deployment directory
echo "📁 Step 2: Creating deployment directory..."
sudo mkdir -p $DEPLOY_DIR
sudo cp -r . $DEPLOY_DIR/
sudo chown -R $USER:$USER $DEPLOY_DIR
cd $DEPLOY_DIR
echo -e "${GREEN}✓ Deployment directory created${NC}"
echo ""

# Step 3: Check for .env file
echo "⚙️  Step 3: Checking environment configuration..."
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo -e "${YELLOW}⚠ .env file not found. Creating from example...${NC}"
    if [ -f "$DEPLOY_DIR/.env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}Please edit $DEPLOY_DIR/.env with your configuration${NC}"
    else
        echo "PORT=$PORT" > .env
        echo "EMAIL_SERVICE=gmail" >> .env
        echo "EMAIL_USER=your-email@gmail.com" >> .env
        echo "EMAIL_PASS=your-app-password" >> .env
        echo -e "${YELLOW}Created basic .env file. Please configure it!${NC}"
    fi
else
    echo -e "${GREEN}✓ .env file found${NC}"
fi
echo ""

# Step 4: Install PM2 if not installed
echo "🔄 Step 4: Setting up PM2 process manager..."
if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2..."
    sudo npm install -g pm2
    echo -e "${GREEN}✓ PM2 installed${NC}"
else
    echo -e "${GREEN}✓ PM2 already installed${NC}"
fi

# Start application with PM2
echo "Starting application with PM2..."
pm2 delete job-search 2>/dev/null || true
pm2 start server.js --name job-search
pm2 save
echo -e "${GREEN}✓ Application started with PM2${NC}"
echo ""

# Step 5: Install and configure Apache2
echo "🌐 Step 5: Configuring Apache2..."

# Check if Apache2 is installed
if ! command -v apache2 &> /dev/null; then
    echo "Installing Apache2..."
    sudo apt-get update
    sudo apt-get install -y apache2
fi

# Enable required modules
echo "Enabling Apache modules..."
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo a2enmod rewrite
sudo a2enmod ssl
echo -e "${GREEN}✓ Apache modules enabled${NC}"

# Create Apache configuration
echo "Creating Apache virtual host configuration..."
APACHE_CONFIG="/etc/apache2/sites-available/job-search.conf"

sudo tee $APACHE_CONFIG > /dev/null <<EOF
<VirtualHost *:80>
    ServerName $DOMAIN
    ServerAlias www.$DOMAIN

    ProxyPreserveHost On
    ProxyPass / http://localhost:$PORT/
    ProxyPassReverse / http://localhost:$PORT/

    ErrorLog \${APACHE_LOG_DIR}/job-search-error.log
    CustomLog \${APACHE_LOG_DIR}/job-search-access.log combined
</VirtualHost>
EOF

echo -e "${GREEN}✓ Apache configuration created${NC}"

# Enable site
echo "Enabling Apache site..."
sudo a2ensite job-search.conf
sudo a2dissite 000-default.conf 2>/dev/null || true
sudo systemctl reload apache2
echo -e "${GREEN}✓ Apache site enabled${NC}"
echo ""

# Step 6: SSL Setup with Let's Encrypt
echo "🔒 Step 6: Setting up SSL with Let's Encrypt..."
read -p "Do you want to set up SSL with Let's Encrypt? (y/n): " SETUP_SSL

if [ "$SETUP_SSL" = "y" ] || [ "$SETUP_SSL" = "Y" ]; then
    # Check if certbot is installed
    if ! command -v certbot &> /dev/null; then
        echo "Installing Certbot..."
        sudo apt-get install -y certbot python3-certbot-apache
    fi

    echo "Obtaining SSL certificate..."
    echo -e "${YELLOW}Note: You need to have your domain pointing to this server's IP address${NC}"
    read -p "Press Enter to continue with SSL setup..."
    
    sudo certbot --apache -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN || {
        echo -e "${YELLOW}SSL setup failed. You can run this manually later:${NC}"
        echo "sudo certbot --apache -d $DOMAIN -d www.$DOMAIN"
    }
    
    echo -e "${GREEN}✓ SSL configured${NC}"
else
    echo -e "${YELLOW}⚠ SSL setup skipped. You can set it up later with:${NC}"
    echo "sudo certbot --apache -d $DOMAIN -d www.$DOMAIN"
fi
echo ""

# Step 7: Configure firewall (if ufw is available)
if command -v ufw &> /dev/null; then
    echo "🔥 Step 7: Configuring firewall..."
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    sudo ufw allow $PORT/tcp
    echo -e "${GREEN}✓ Firewall configured${NC}"
    echo ""
fi

# Step 8: Final instructions
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Your Job Search Platform is now deployed!"
echo ""
echo "📍 Deployment Details:"
echo "   - Directory: $DEPLOY_DIR"
echo "   - Domain: $DOMAIN"
echo "   - Port: $PORT"
echo "   - PM2 Process: job-search"
echo ""
echo "📋 Next Steps:"
echo "   1. Edit $DEPLOY_DIR/.env with your configuration"
echo "   2. Restart the application: pm2 restart job-search"
echo "   3. Visit http://$DOMAIN in your browser"
echo ""
echo "🔧 Useful Commands:"
echo "   - View logs: pm2 logs job-search"
echo "   - Restart: pm2 restart job-search"
echo "   - Stop: pm2 stop job-search"
echo "   - Apache logs: sudo tail -f /var/log/apache2/job-search-*.log"
echo ""
echo "📚 Documentation: See SETUP.md for detailed information"
echo ""
