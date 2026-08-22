// Jenkins pipeline for freecad-web: fetch the prebuilt WASM artifacts from the latest GitHub
// Release, GL-patch and package them into the nginx image (infra/Dockerfile), and deploy to the
// test app server. Never touches production (freecad.virtastic.app is the OVH/GitHub-Actions path).
//
// Unlike the game ports, freecad does NOT compile in CI — the toolchain build is out-of-band and
// publishes a Release. So this job is fetch -> patch+package -> deploy, not compile.
pipeline {
  agent any
  options { timestamps(); disableConcurrentBuilds(); timeout(time: 45, unit: 'MINUTES') }
  environment {
    TAG       = 'freecad:test'
    NAME      = 'freecad-test'
    PORT      = '8084'
    TEST_HOST = 'testapp@192.168.1.131'
    SSH_KEY   = '/var/jenkins_home/.ssh/id_ed25519'   // the container's test-server deploy key
    REPO      = 'Virtastic/freecad-web'
    SMOKE_URL = 'https://freecad.dev.virtastic.app'
  }
  stages {
    stage('Fetch release artifacts') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'github-virtastic',
                                           usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
          sh 'GH_TOKEN="$GH_TOKEN" REPO="$REPO" ci/jenkins/fetch-artifacts.sh'
        }
      }
    }
    stage('GL-patch + build image') { steps { sh 'TAG="$TAG" ci/jenkins/build-image.sh' } }
    stage('Deploy to test server') {
      steps { sh 'TEST_HOST="$TEST_HOST" SSH_KEY="$SSH_KEY" TAG="$TAG" NAME="$NAME" PORT="$PORT" ci/jenkins/deploy-test.sh' }
    }
    stage('Smoke') {
      steps {
        sh '''
          if [ -n "$SMOKE_URL" ] && curl -sf -o /dev/null --max-time 8 "$SMOKE_URL/" 2>/dev/null; then
            ci/jenkins/smoke-test.sh "$SMOKE_URL"
          else
            echo "public origin not reachable yet; smoke-testing the container directly"
            ci/jenkins/smoke-test.sh "http://192.168.1.131:$PORT"
          fi
        '''
      }
    }
  }
  post {
    success { echo "freecad built and deployed to the test server on :${env.PORT}" }
    failure { echo 'freecad test pipeline failed — see stage logs' }
  }
}
