# Use the python:3.13-bookworm as the base image
FROM python:3.13-bookworm

# Set environment variables to prevent Python from writing .pyc files and to enable unbuffered output
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt file to the working directory
COPY requirements.txt /app/

# Install dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the application code, so deployment files next to it (env files holding a token, compose
# overrides) never end up in the image
COPY main.py /app/

# Expose the port FastAPI will run on (default is 39501)
EXPOSE 39501

# Command to run the FastAPI application using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "39501"]
