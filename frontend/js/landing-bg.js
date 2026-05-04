// 3D Animated Mesh Background for Research Agent Landing Page
// Monochrome gray floating 3D mesh

(function() {
    const canvas = document.getElementById('lp-canvas');
    if (!canvas) {
        console.error('[Landing BG] Canvas not found');
        return;
    }
    
    if (typeof THREE === 'undefined') {
        console.error('[Landing BG] THREE.js not loaded');
        return;
    }
    
    // Scene
    const scene = new THREE.Scene();
    
    // Camera
    const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 50;
    
    // Renderer
    const renderer = new THREE.WebGLRenderer({ 
        canvas: canvas,
        alpha: true,
        antialias: true
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    
    // Gray colors (brighter for visibility)
    const grayColors = [0x555555, 0x666666, 0x777777, 0x888888, 0x999999];
    
    // Create mesh planes
    const meshes = [];
    const meshCount = 25;
    
    for (let i = 0; i < meshCount; i++) {
        const width = Math.random() * 15 + 8;
        const height = Math.random() * 15 + 8;
        const geometry = new THREE.PlaneGeometry(width, height, 8, 8);
        
        const color = grayColors[Math.floor(Math.random() * grayColors.length)];
        const material = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.3,
            wireframe: true,
            side: THREE.DoubleSide
        });
        
        const mesh = new THREE.Mesh(geometry, material);
        
        // Position in a 3D space
        mesh.position.x = (Math.random() - 0.5) * 100;
        mesh.position.y = (Math.random() - 0.5) * 80;
        mesh.position.z = (Math.random() - 0.5) * 50 - 20;
        
        // Random rotation
        mesh.rotation.x = Math.random() * Math.PI;
        mesh.rotation.y = Math.random() * Math.PI;
        
        // Store animation data
        mesh.userData = {
            rotSpeedX: (Math.random() - 0.5) * 0.008,
            rotSpeedY: (Math.random() - 0.5) * 0.008,
            floatSpeed: Math.random() * 0.5 + 0.5,
            floatOffset: Math.random() * Math.PI * 2,
            originalY: mesh.position.y
        };
        
        meshes.push(mesh);
        scene.add(mesh);
    }
    
    // Create particles
    const particleCount = 200;
    const particleGeometry = new THREE.BufferGeometry();
    const particlePositions = new Float32Array(particleCount * 3);
    
    for (let i = 0; i < particleCount * 3; i += 3) {
        particlePositions[i] = (Math.random() - 0.5) * 120;
        particlePositions[i + 1] = (Math.random() - 0.5) * 100;
        particlePositions[i + 2] = (Math.random() - 0.5) * 60 - 30;
    }
    
    particleGeometry.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    
    const particleMaterial = new THREE.PointsMaterial({
        color: 0x888888,
        size: 2,
        transparent: true,
        opacity: 0.7
    });
    
    const particles = new THREE.Points(particleGeometry, particleMaterial);
    scene.add(particles);
    
    // Mouse tracking
    let mouseX = 0;
    let mouseY = 0;
    
    document.addEventListener('mousemove', (e) => {
        mouseX = (e.clientX / window.innerWidth) * 2 - 1;
        mouseY = -(e.clientY / window.innerHeight) * 2 + 1;
    });
    
    // Animation loop
    let time = 0;
    
    function animate() {
        requestAnimationFrame(animate);
        
        time += 0.01;
        
        // Animate meshes
        meshes.forEach((mesh, index) => {
            mesh.rotation.x += mesh.userData.rotSpeedX;
            mesh.rotation.y += mesh.userData.rotSpeedY;
            
            // Floating motion
            const floatY = Math.sin(time * mesh.userData.floatSpeed + mesh.userData.floatOffset) * 2;
            mesh.position.y = mesh.userData.originalY + floatY;
        });
        
        // Rotate particles slowly
        particles.rotation.y += 0.0002;
        particles.rotation.x += 0.0001;
        
        // Camera follows mouse slightly
        camera.position.x += (mouseX * 5 - camera.position.x) * 0.02;
        camera.position.y += (mouseY * 5 - camera.position.y) * 0.02;
        camera.lookAt(scene.position);
        
        renderer.render(scene, camera);
    }
    
    // Start
    animate();
    
    // Resize handler
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });
    
    console.log('[Landing BG] Started successfully');
})();